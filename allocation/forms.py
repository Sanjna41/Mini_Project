from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    Faculty,
    PhDScholar,
    Classroom,
    ExamSchedule,
    UFMRecord,
    Section,
    Subject,
    Availability, ReplacementRequest, ExamSession,
)


class StaffAuthenticationForm(AuthenticationForm):
    """Only staff users can enter the staff-only duty management system."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff and not (hasattr(user, 'faculty_profile') or hasattr(user, 'phd_profile')):
            raise ValidationError(
                'This account is not permitted to access the staff portal.',
                code='not_staff',
            )


class FacultyForm(forms.ModelForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Subjects this faculty member is qualified to teach or invigilate.',
        label='Subject expertise',
    )

    class Meta:
        model = Faculty
        fields = ['name', 'employee_id', 'email', 'department', 'contact', 'designation', 'duty_quota', 'subject']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['subject'] = self.instance.subjects.order_by('name').first()

    def save(self, commit=True):
        faculty = super().save(commit=False)
        if commit:
            faculty.save()
            faculty.subjects.set([self.cleaned_data['subject']] if self.cleaned_data['subject'] else [])
        else:
            self.save_m2m = lambda: faculty.subjects.set(
                [self.cleaned_data['subject']] if self.cleaned_data['subject'] else []
            )
        return faculty


class PhDScholarForm(forms.ModelForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Subject',
    )

    class Meta:
        model = PhDScholar
        fields = ['name', 'scholar_id', 'email', 'department', 'academic_year', 'contact', 'duty_quota', 'subject']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['subject'] = self.instance.subjects.order_by('name').first()

    def save(self, commit=True):
        scholar = super().save(commit=False)
        if commit:
            scholar.save()
            scholar.subjects.set([self.cleaned_data['subject']] if self.cleaned_data['subject'] else [])
        else:
            self.save_m2m = lambda: scholar.subjects.set(
                [self.cleaned_data['subject']] if self.cleaned_data['subject'] else []
            )
        return scholar


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['name', 'rows', 'columns']

    def clean(self):
        cleaned_data = super().clean()
        for field in ('rows', 'columns'):
            if cleaned_data.get(field) is not None and cleaned_data[field] < 1:
                self.add_error(field, 'Must be a positive integer.')
        return cleaned_data


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'coordinator']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'coordinator': forms.Select(attrs={'class': 'form-select'}),
        }
        help_texts = {
            'coordinator': 'This faculty member must receive duty for this subject. Missing or conflicting assignments are reported during allocation.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['coordinator'].queryset = Faculty.objects.order_by('name')
        self.fields['coordinator'].required = False

    def save(self, commit=True):
        previous = self.instance.coordinator_id
        subject = super().save(commit=commit)
        changed = not self.instance.pk or previous != subject.coordinator_id
        if commit and changed:
            status = (ExamSchedule.CoordinatorStatus.PENDING if subject.coordinator_id
                      else ExamSchedule.CoordinatorStatus.UNRESOLVED)
            note = ('Coordinator changed; rerun duty allocation to verify availability and assign the duty.'
                    if subject.coordinator_id else 'No faculty coordinator is configured for this subject.')
            ExamSchedule.objects.filter(subject=subject).update(
                coordinator_status=status, coordinator_note=note,
            )
        return subject


class ExamScheduleForm(forms.ModelForm):
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.all().order_by('name'), required=False,
        help_text='Select sections in their required seating order.'
    )
    class Meta:
        model = ExamSchedule
        fields = ['examination_type', 'date', 'slot', 'start_time', 'end_time', 'reporting_time', 'instructions', 'subject', 'session', 'sections']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'reporting_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def save(self, commit=True):
        exam = super().save(commit=False)
        needs_coordinator_review = (not self.instance.pk or bool(
            {'date', 'slot', 'start_time', 'end_time', 'subject'} & set(self.changed_data)
        ))

        def save_sections():
            selected_sections = {
                section.pk: section for section in self.cleaned_data['sections']
            }
            selected_ids = []
            for value in self.data.getlist('sections'):
                section_id = int(value)
                if section_id in selected_sections and section_id not in selected_ids:
                    selected_ids.append(section_id)
            with transaction.atomic():
                exam.exam_sections.all().delete()
                for position, section_id in enumerate(selected_ids, start=1):
                    exam.exam_sections.create(section_id=section_id, position=position)

        self.save_m2m = save_sections
        if commit:
            with transaction.atomic():
                if needs_coordinator_review:
                    exam.coordinator_status = (ExamSchedule.CoordinatorStatus.PENDING
                        if exam.subject_id else ExamSchedule.CoordinatorStatus.NOT_REQUIRED)
                    exam.coordinator_note = ('Schedule changed; rerun duty allocation to verify and assign the subject coordinator.'
                        if exam.subject_id else '')
                exam.save()
                save_sections()
        return exam


class UFMRecordForm(forms.ModelForm):
    class Meta:
        model = UFMRecord
        fields = ['faculty', 'phd_scholar', 'exam_schedule', 'count', 'notes']

    def clean(self):
        cleaned_data = super().clean()
        if bool(cleaned_data.get('faculty')) == bool(cleaned_data.get('phd_scholar')):
            raise forms.ValidationError('Select exactly one faculty member or PhD scholar.')
        return cleaned_data


class AvailabilityForm(forms.ModelForm):
    class Meta:
        model = Availability
        fields = ['date', 'start_time', 'end_time', 'is_available', 'note']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}),
                   'start_time': forms.TimeInput(attrs={'type': 'time'}),
                   'end_time': forms.TimeInput(attrs={'type': 'time'})}

    def clean(self):
        data = super().clean()
        if data.get('start_time') and data.get('end_time') and data['start_time'] >= data['end_time']:
            raise ValidationError('End time must be after start time.')
        return data


class ReplacementRequestForm(forms.ModelForm):
    class Meta:
        model = ReplacementRequest
        fields = ['target_faculty', 'target_phd_scholar']

    def clean(self):
        data = super().clean()
        if bool(data.get('target_faculty')) == bool(data.get('target_phd_scholar')):
            raise ValidationError('Choose exactly one replacement person.')
        return data


class ExamSessionForm(forms.ModelForm):
    class Meta:
        model = ExamSession
        fields = ['name', 'starts_on', 'ends_on']
        widgets = {'starts_on': forms.DateInput(attrs={'type': 'date'}), 'ends_on': forms.DateInput(attrs={'type': 'date'})}


class AnnouncementForm(forms.Form):
    message = forms.CharField(min_length=5, max_length=1000, widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}))
    faculty = forms.ModelMultipleChoiceField(queryset=Faculty.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}))
    phd_scholars = forms.ModelMultipleChoiceField(queryset=PhDScholar.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['faculty'].queryset = Faculty.objects.order_by('name')
        self.fields['phd_scholars'].queryset = PhDScholar.objects.order_by('name')

    def clean(self):
        data = super().clean()
        if not data.get('faculty') and not data.get('phd_scholars'):
            raise ValidationError('Select at least one faculty member or PhD scholar.')
        return data

