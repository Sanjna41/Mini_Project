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
)


class StaffAuthenticationForm(AuthenticationForm):
    """Only staff users can enter the staff-only duty management system."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(
                'This account is not permitted to access the staff portal.',
                code='not_staff',
            )


class FacultyForm(forms.ModelForm):
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Choose the subject this faculty member coordinates.',
        label='Subject',
    )

    class Meta:
        model = Faculty
        fields = ['name', 'email', 'designation', 'duty_quota', 'subject']

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
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Subject',
    )

    class Meta:
        model = PhDScholar
        fields = ['name', 'email', 'duty_quota', 'subject']

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


class ExamScheduleForm(forms.ModelForm):
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.all().order_by('name'), required=False,
        help_text='Select sections in their required seating order.'
    )
    class Meta:
        model = ExamSchedule
        fields = ['date', 'slot', 'start_time', 'end_time', 'subject', 'sections']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def save(self, commit=True):
        exam = super().save(commit=False)

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

