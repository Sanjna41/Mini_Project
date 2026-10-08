from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
import csv
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .allocation_algorithm import allocate_all_duties
from .csv_merge import merge_seating_csv
from .seating_allocator import (
    InsufficientCapacityError, RoomInput, StudentInput, allocate_seats,
    contiguous_ranges,
)
from .decorators import staff_required
from .forms import (
    ClassroomForm,
    ExamScheduleForm,
    FacultyForm,
    PhDScholarForm,
    UFMRecordForm,
)
from .models import (
    Classroom,
    DutyAllocation,
    ExamSchedule,
    Faculty,
    PhDScholar,
    UFMRecord,
    ExamSection,
    Seating,
    SeatingAllotment,
    Student,
    Section,
)
from .notifications import send_allocation_emails


@staff_required
def dashboard(request):
    context = {
        'faculty_count': Faculty.objects.count(),
        'phd_count': PhDScholar.objects.count(),
        'classroom_count': Classroom.objects.count(),
        'exam_count': ExamSchedule.objects.count(),
        'allocation_count': DutyAllocation.objects.count(),
        'ufm_count': UFMRecord.objects.count(),
    }

    duty_counts = (
        Faculty.objects.annotate(duty_total=Count('duty_allocations')).order_by('name')
    )
    context['chart_labels'] = [f.name for f in duty_counts]
    context['chart_data'] = [f.duty_total for f in duty_counts]

    return render(request, 'allocation/dashboard.html', context)


@staff_required
def faculty_list(request):
    faculty = Faculty.objects.all().order_by('name')
    return render(request, 'allocation/faculty_list.html', {'faculty_list': faculty})


@staff_required
def faculty_create(request):
    if request.method == 'POST':
        form = FacultyForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faculty added.')
            return redirect('allocation:faculty_list')
    else:
        form = FacultyForm()
    return render(
        request,
        'allocation/faculty_form.html',
        {'form': form, 'title': 'Add Faculty'},
    )


@staff_required
def faculty_edit(request, pk):
    faculty = get_object_or_404(Faculty, pk=pk)
    if request.method == 'POST':
        form = FacultyForm(request.POST, instance=faculty)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faculty updated.')
            return redirect('allocation:faculty_list')
    else:
        form = FacultyForm(instance=faculty)
    return render(
        request,
        'allocation/faculty_form.html',
        {'form': form, 'title': 'Edit Faculty'},
    )


@staff_required
def phd_list(request):
    phds = PhDScholar.objects.all().order_by('name')
    return render(request, 'allocation/phd_list.html', {'phd_list': phds})


@staff_required
def phd_create(request):
    if request.method == 'POST':
        form = PhDScholarForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'PhD Scholar added.')
            return redirect('allocation:phd_list')
    else:
        form = PhDScholarForm()
    return render(
        request, 'allocation/phd_form.html', {'form': form, 'title': 'Add PhD Scholar'}
    )


@staff_required
def phd_edit(request, pk):
    phd = get_object_or_404(PhDScholar, pk=pk)
    if request.method == 'POST':
        form = PhDScholarForm(request.POST, instance=phd)
        if form.is_valid():
            form.save()
            messages.success(request, 'PhD Scholar updated.')
            return redirect('allocation:phd_list')
    else:
        form = PhDScholarForm(instance=phd)
    return render(
        request, 'allocation/phd_form.html', {'form': form, 'title': 'Edit PhD Scholar'}
    )


@staff_required
def classroom_list(request):
    rooms = Classroom.objects.all().order_by('name')
    return render(
        request, 'allocation/classroom_list.html', {'classroom_list': rooms}
    )


@staff_required
def classroom_create(request):
    if request.method == 'POST':
        form = ClassroomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classroom added.')
            return redirect('allocation:classroom_list')
    else:
        form = ClassroomForm()
    return render(
        request,
        'allocation/classroom_form.html',
        {'form': form, 'title': 'Add Classroom'},
    )


@staff_required
def classroom_edit(request, pk):
    room = get_object_or_404(Classroom, pk=pk)
    if request.method == 'POST':
        form = ClassroomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classroom updated.')
            return redirect('allocation:classroom_list')
    else:
        form = ClassroomForm(instance=room)
    return render(
        request,
        'allocation/classroom_form.html',
        {'form': form, 'title': 'Edit Classroom'},
    )


@staff_required
def exam_schedule_list(request):
    exams = ExamSchedule.objects.all()
    return render(request, 'allocation/exam_schedule_list.html', {'exam_list': exams})


@staff_required
def exam_schedule_create(request):
    if request.method == 'POST':
        form = ExamScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Exam schedule added.')
            return redirect('allocation:exam_schedule_list')
    else:
        form = ExamScheduleForm()
    return render(
        request,
        'allocation/exam_schedule_form.html',
        {'form': form, 'title': 'Add Exam Schedule'},
    )


@staff_required
def exam_schedule_edit(request, pk):
    exam = get_object_or_404(ExamSchedule, pk=pk)
    if request.method == 'POST':
        form = ExamScheduleForm(request.POST, instance=exam)
        if form.is_valid():
            form.save()
            messages.success(request, 'Exam schedule updated.')
            return redirect('allocation:exam_schedule_list')
    else:
        form = ExamScheduleForm(instance=exam)
    return render(
        request,
        'allocation/exam_schedule_form.html',
        {'form': form, 'title': 'Edit Exam Schedule'},
    )


@staff_required
def ufm_record_list(request):
    records = UFMRecord.objects.select_related(
        'faculty', 'phd_scholar', 'exam_schedule'
    ).all()
    return render(request, 'allocation/ufm_record_list.html', {'records': records})


@staff_required
def run_allocation(request):
    if request.method == 'POST':
        try:
            created = allocate_all_duties(clear_existing=True)
            send_allocation_emails(request)
            messages.success(
                request, f'Allocation complete. Created {len(created)} duties.'
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect('allocation:allocation_result')
    return render(request, 'allocation/run_allocation_confirm.html', {
        'exam_count': ExamSchedule.objects.count(),
    })


@staff_required
@require_POST
def run_allocation_ajax(request):
    try:
        created = allocate_all_duties(clear_existing=True)
        return JsonResponse({'status': 'ok', 'created': len(created)})
    except ValidationError as exc:
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)


@staff_required
def ufm_record_create(request):
    if request.method == 'POST':
        form = UFMRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'UFM record added.')
            return redirect('allocation:ufm_record_list')
    else:
        form = UFMRecordForm()
    return render(
        request,
        'allocation/ufm_record_form.html',
        {'form': form, 'title': 'Add UFM Record'},
    )



@staff_required
def export_allocation_csv(request):
    import csv

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="duty_allocation.csv"'

    allocations = DutyAllocation.objects.select_related(
        'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
    ).order_by(
        'exam_schedule__date', 'exam_schedule__slot', 'classroom__name'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            'S.No',
            'Name',
            'Designation',
            'Date',
            'Time Slot',
            'Room Number',
            'Role Type',
        ]
    )

    for idx, a in enumerate(allocations, start=1):
        person = a.faculty or a.phd_scholar
        if a.faculty:
            designation = a.faculty.get_designation_display()
        else:
            designation = 'PhD Scholar'
        writer.writerow(
            [
                idx,
                person.name if person else '',
                designation,
                a.exam_schedule.date,
                a.exam_schedule.get_slot_display(),
                a.classroom.name,
                a.get_role_type_display(),
            ]
        )

    return response


@staff_required
def duty_order_pdf(request):
    allocations = DutyAllocation.objects.select_related(
        'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
    ).order_by('exam_schedule__date', 'exam_schedule__slot', 'classroom__name')
    rows = []
    for index, allocation in enumerate(allocations, start=1):
        person = allocation.faculty or allocation.phd_scholar
        designation = allocation.faculty.get_designation_display() if allocation.faculty else 'PhD Scholar'
        rows.append([
            index, person.name if person else '', designation,
            allocation.exam_schedule.date.strftime('%d %b %Y'),
            allocation.exam_schedule.get_slot_display(), allocation.classroom.name,
            allocation.get_role_type_display(),
        ])
    return _render_table_pdf(
        'duty_order.pdf', 'Exam Duty Order', 'Final invigilation duty allocation',
        ['No.', 'Name', 'Designation', 'Date', 'Slot', 'Room', 'Role'], rows,
        [10, 38, 35, 25, 25, 35, 32],
    )


def _render_table_pdf(filename, title, subtitle, headers, rows, column_widths_mm):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    cell_style = styles['BodyText']
    cell_style.fontSize = 8
    cell_style.leading = 10
    header_style = ParagraphStyle(
        'TableHeader', parent=cell_style, fontName='Helvetica-Bold',
        fontSize=8, leading=10,
    )
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title,
    )
    story = [
        Paragraph(escape(title), styles['Title']),
        Paragraph(escape(subtitle), styles['Normal']),
        Spacer(1, 8 * mm),
    ]
    table_data = [[Paragraph(escape(str(value)), header_style) for value in headers]]
    table_data.extend([
        [Paragraph(escape(str(value)), cell_style) for value in row]
        for row in rows
    ] or [[Paragraph('No records available.', cell_style)] + [''] * (len(headers) - 1)])
    table = LongTable(
        table_data,
        colWidths=[width * mm for width in column_widths_mm],
        repeatRows=1,
        hAlign='LEFT',
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16324f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#b7c4d1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    document.build(story)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@staff_required
def seating_plan(request):
    plans = []
    exams = ExamSchedule.objects.prefetch_related('exam_sections__section').all()

    for exam in exams:
        room_entries = []
        rooms = Classroom.objects.filter(seatings__exam_schedule=exam).distinct().order_by('name')
        for room in rooms:
            seats = list(Seating.objects.filter(exam_schedule=exam, classroom=room).select_related('section').order_by('seat_no'))
            ranges = SeatingAllotment.objects.filter(exam_schedule=exam, classroom=room).select_related('section')
            room_entries.append(
                {
                    'classroom': room,
                    'capacity': room.capacity,
                    'ranges': ranges,
                    'grid': [[next((seat for seat in seats if seat.row_no == row and seat.col_no == col), None)
                              for col in range(1, room.columns + 1)] for row in range(1, room.rows + 1)],
                }
            )
        plans.append({'exam': exam, 'rooms': room_entries})

    return render(request, 'allocation/seating_plan.html', {
        'seating_plans': plans,
        'exams': exams,
        'classrooms': Classroom.objects.all().order_by('name'),
    })


def _seating_export_rows(exam):
    seatings = list(
        Seating.objects.filter(exam_schedule=exam)
        .select_related('classroom', 'section')
        .order_by('classroom__name', 'seat_no')
    )
    names = {
        (student.section_id, student.roll_no): student.name
        for student in Student.objects.filter(
            section_id__in={seat.section_id for seat in seatings},
            roll_no__in={seat.roll_no for seat in seatings},
        )
    }
    return seatings, names


@staff_required
def export_seating_plan_csv(request, exam_id):
    exam = get_object_or_404(ExamSchedule, pk=exam_id)
    seatings, names = _seating_export_rows(exam)
    if not seatings:
        return HttpResponse('No seating plan has been generated for this exam.', status=404)

    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Section', 'Roll No', 'Student Name', 'Room', 'Seat No', 'Row', 'Column'])
    for seat in seatings:
        writer.writerow([
            seat.section.name, seat.roll_no, names.get((seat.section_id, seat.roll_no), ''),
            seat.classroom.name, seat.seat_no, seat.row_no, seat.col_no,
        ])
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="seating_plan_{exam.pk}.csv"'
    return response


@staff_required
def export_seating_plan_pdf(request, exam_id):
    exam = get_object_or_404(ExamSchedule, pk=exam_id)
    seatings, names = _seating_export_rows(exam)
    if not seatings:
        return HttpResponse('No seating plan has been generated for this exam.', status=404)
    rows = [[
        seat.section.name, seat.roll_no, names.get((seat.section_id, seat.roll_no), ''),
        seat.classroom.name, seat.seat_no, seat.row_no, seat.col_no,
    ] for seat in seatings]
    subtitle = f'{exam.date:%d %b %Y} | {exam.get_slot_display()} | {exam.subject or "Exam"}'
    return _render_table_pdf(
        f'seating_plan_{exam.pk}.pdf', 'Exam Seating Plan', subtitle,
        ['Section', 'Roll No.', 'Student Name', 'Room', 'Seat', 'Row', 'Column'],
        rows, [32, 22, 55, 42, 18, 18, 18],
    )


@staff_required
@require_POST
def generate_seating(request):
    exam = get_object_or_404(ExamSchedule, pk=request.POST.get('exam_id'))
    room_ids = request.POST.getlist('classrooms')
    rooms = list(Classroom.objects.filter(pk__in=room_ids).order_by('name'))
    if not rooms:
        messages.error(request, 'Select at least one classroom.')
        return redirect('allocation:seating_plan')
    fill_order = request.POST.get('fill_order', 'row')
    sections = []
    for exam_section in exam.exam_sections.select_related('section').order_by('position'):
        students = [StudentInput(s.roll_no, exam_section.section_id, exam_section.section.name)
                    for s in exam_section.section.students.all().order_by('roll_no')]
        sections.append((exam_section.section_id, exam_section.section.name, students))
    if not sections:
        messages.error(request, 'Select at least one section for this exam before generating seating.')
        return redirect('allocation:seating_plan')
    try:
        assignments = allocate_seats(
            sections, [RoomInput(r.id, r.name, r.rows, r.columns) for r in rooms], fill_order
        )
    except (InsufficientCapacityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect('allocation:seating_plan')
    with transaction.atomic():
        Seating.objects.filter(exam_schedule=exam).delete()
        SeatingAllotment.objects.filter(exam_schedule=exam).delete()
        Seating.objects.bulk_create([
            Seating(exam_schedule=exam, classroom_id=item.room_id,
                    section_id=item.student.section_id, seat_no=item.seat_no,
                    row_no=item.row_no, col_no=item.col_no, roll_no=item.student.roll_no)
            for item in assignments
        ])
        SeatingAllotment.objects.bulk_create([
            SeatingAllotment(exam_schedule=exam, classroom_id=item['room_id'],
                             section_id=item['section_id'], from_roll_no=item['from_roll_no'],
                             to_roll_no=item['to_roll_no'])
            for item in contiguous_ranges(assignments)
        ])
    messages.success(request, f'Seating generated for {len(assignments)} students.')
    return redirect('allocation:seating_plan')


@staff_required
def seating_search(request):
    roll_no = request.GET.get('roll_no', '').strip()
    seatings = Seating.objects.none()
    if roll_no:
        seatings = Seating.objects.filter(roll_no=roll_no).select_related(
            'exam_schedule', 'classroom', 'section'
        ).order_by('exam_schedule__date', 'exam_schedule__slot', 'section__name')
        if not seatings.exists():
            messages.warning(request, f'No seating allotment found for roll number {roll_no}.')
    return render(request, 'allocation/seating_search.html', {'seatings': seatings, 'roll_no': roll_no})


@staff_required
@require_POST
def export_seating_csv(request):
    upload = request.FILES.get('student_csv')
    exam = get_object_or_404(ExamSchedule, pk=request.POST.get('exam_id'))
    if not upload or upload.size > 5 * 1024 * 1024:
        return HttpResponseBadRequest('Upload a CSV file no larger than 5 MB.')
    try:
        content = upload.read().decode('utf-8-sig')
        seating_by_roll = {
            (item.section.name, str(item.roll_no)): {
                'room_name': item.classroom.name, 'row': item.row_no,
                'column': item.col_no, 'seat_no': item.seat_no,
            }
            for item in Seating.objects.filter(exam_schedule=exam).select_related('classroom', 'section')
        }
        merged, unallotted = merge_seating_csv(__import__('io').StringIO(content), seating_by_roll)
    except (UnicodeDecodeError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    response = HttpResponse(merged, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_seating.csv"'
    if unallotted:
        response['X-Unallotted-Rolls'] = ','.join(unallotted)[:4000]
        messages.warning(request, 'Unallotted roll numbers: ' + ', '.join(filter(None, unallotted)))
    return response


@staff_required
@require_POST
def import_students_csv(request):
    import csv
    import io

    upload = request.FILES.get('student_csv')
    if not upload or upload.size > 5 * 1024 * 1024:
        return HttpResponseBadRequest('Upload a CSV file no larger than 5 MB.')
    try:
        rows = list(csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig'))))
        if not rows or not {'roll_no', 'section'}.issubset(rows[0]):
            raise ValueError('CSV must include roll_no and section columns.')
        students = []
        sections = {}
        for number, row in enumerate(rows, start=2):
            section_name = row.get('section', '').strip()
            if not section_name:
                raise ValueError(f'Row {number}: section is required.')
            try:
                roll_no = int(row.get('roll_no', ''))
            except ValueError as exc:
                raise ValueError(f'Row {number}: roll_no must be a positive integer.') from exc
            if roll_no < 1:
                raise ValueError(f'Row {number}: roll_no must be a positive integer.')
            sections.setdefault(section_name, None)
            students.append((section_name, roll_no, row.get('name', '').strip()))
        with transaction.atomic():
            for name in sections:
                sections[name], _ = Section.objects.get_or_create(name=name)
            for section_name, roll_no, name in students:
                Student.objects.update_or_create(
                    section=sections[section_name], roll_no=roll_no, defaults={'name': name}
                )
    except (UnicodeDecodeError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, f'Imported {len(students)} students.')
    return redirect('allocation:seating_plan')



@staff_required
def allocation_result(request):
    q = request.GET.get('q', '').strip()
    date_filter = request.GET.get('date', '').strip()
    slot_filter = request.GET.get('slot', '').strip().upper()
    allocations = DutyAllocation.objects.select_related(
        'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
    ).order_by('exam_schedule__date', 'exam_schedule__slot', 'classroom__name')
    if q:
        allocations = allocations.filter(
            Q(faculty__name__icontains=q)
            | Q(phd_scholar__name__icontains=q)
            | Q(classroom__name__icontains=q)
        )
    parsed_date = parse_date(date_filter) if date_filter else None
    if parsed_date:
        allocations = allocations.filter(exam_schedule__date=parsed_date)
    if slot_filter in (ExamSchedule.Slot.MORNING, ExamSchedule.Slot.EVENING):
        allocations = allocations.filter(exam_schedule__slot=slot_filter)

    paginator = Paginator(allocations, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'allocation/allocation_result.html', {
        'page_obj': page_obj,
        'q': q,
        'date_filter': date_filter,
        'slot_filter': slot_filter,
    })

