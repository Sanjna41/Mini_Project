from django import forms

from .models import (
    Faculty,
    PhDScholar,
    Classroom,
    ExamSchedule,
    UFMRecord,
    Section,
    Subject,
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
        fields = ['name', 'email', 'designation', 'duty_quota']

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
        fields = ['name', 'email', 'duty_quota']

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
        exam = super().save(commit=commit)
        if commit:
            selected_ids = [int(value) for value in self.data.getlist('sections')]
            exam.exam_sections.all().delete()
            for position, section_id in enumerate(selected_ids, start=1):
                if section_id in {section.id for section in self.cleaned_data['sections']}:
                    exam.exam_sections.create(section_id=section_id, position=position)
        return exam


class UFMRecordForm(forms.ModelForm):
    class Meta:
        model = UFMRecord
        fields = ['faculty', 'phd_scholar', 'exam_schedule', 'count', 'notes']

