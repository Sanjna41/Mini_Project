"""ReportLab rendering for official, room-wise examination duty orders."""
from collections import OrderedDict
from datetime import date as datetime_date
from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Q
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import landscape
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, LongTable, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from .models import DutyAllocation, ExamSchedule

INK = colors.HexColor('#17283b')
ACCENT = colors.HexColor('#294b68')
RULE = colors.HexColor('#9ba8b4')
PALE = colors.HexColor('#eef2f5')


class DutySectionMarker(Flowable):
    """Remember the active date/shift so continuation pages retain context."""
    def __init__(self, label):
        super().__init__()
        self.label = label
        self.width = 0
        self.height = 0

    def draw(self):
        self.canv._doctemplate._duty_group_header = self.label


def allocation_queryset():
    return DutyAllocation.objects.select_related(
        'exam_schedule', 'exam_schedule__session', 'exam_schedule__subject',
        'exam_schedule__subject__coordinator', 'subject',
        'classroom', 'faculty', 'phd_scholar'
    ).filter(Q(faculty__isnull=False) | Q(phd_scholar__isnull=False)).order_by('exam_schedule__date', 'exam_schedule__start_time',
               'exam_schedule__slot', 'classroom__name',
               'faculty__name', 'phd_scholar__name')


def _pdf_response(story, filename, title):
    output = BytesIO()
    styles = getSampleStyleSheet()
    doc = BaseDocTemplate(output, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                          topMargin=48*mm, bottomMargin=27*mm, title=title,
                          author=getattr(settings, 'INSTITUTE_NAME', ''))
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='body')
    doc.addPageTemplates(PageTemplate(id='official', frames=frame, onPage=_page_chrome))
    doc.build(story)
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _page_chrome(canvas, doc):
    canvas.saveState()
    width, height = A4
    institute = getattr(settings, 'INSTITUTE_NAME', 'MAULANA AZAD NATIONAL INSTITUTE OF TECHNOLOGY BHOPAL')
    dept = getattr(settings, 'EXAM_DUTY_DEPARTMENT', 'DEPARTMENT OF COMPUTER SCIENCE & ENGINEERING')
    canvas.setFillColor(INK)
    canvas.setFont('Helvetica-Bold', 13)
    canvas.drawCentredString(width/2, height-17*mm, institute.upper())
    canvas.setFont('Helvetica-Bold', 9)
    canvas.drawCentredString(width/2, height-23*mm, dept.upper())
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.1)
    canvas.line(doc.leftMargin, height-28*mm, width-doc.rightMargin, height-28*mm)
    if doc.page > 1:
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(INK)
        canvas.drawString(doc.leftMargin, height-35*mm, 'EXAMINATION DUTY ORDER')
        group_header = getattr(doc, '_duty_group_header', '')
        if group_header:
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(colors.HexColor('#52606d'))
            canvas.drawString(doc.leftMargin, height-41*mm, group_header)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(.5)
    canvas.line(doc.leftMargin, 19*mm, width-doc.rightMargin, 19*mm)
    canvas.setFillColor(colors.HexColor('#52606d'))
    canvas.setFont('Helvetica', 8)
    canvas.drawString(doc.leftMargin, 14*mm, 'Department of Computer Science & Engineering')
    canvas.drawRightString(width-doc.rightMargin, 14*mm, f'Page {doc.page}')
    canvas.restoreState()


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('OfficialTitle', parent=base['Title'], fontName='Helvetica-Bold',
            fontSize=17, leading=21, textColor=INK, alignment=TA_CENTER, spaceAfter=4*mm),
        'meta': ParagraphStyle('OfficialMeta', parent=base['Normal'], fontSize=9, leading=13,
            textColor=INK, alignment=TA_CENTER),
        'date': ParagraphStyle('DateSection', parent=base['Heading2'], fontName='Helvetica-Bold',
            fontSize=12, leading=15, textColor=INK, spaceBefore=5*mm, spaceAfter=1*mm,
            keepWithNext=True),
        'room': ParagraphStyle('RoomHeading', parent=base['Heading3'], fontName='Helvetica-Bold',
            fontSize=10, leading=13, textColor=ACCENT, spaceBefore=3*mm, spaceAfter=1.5*mm,
            keepWithNext=True),
        'body': ParagraphStyle('OfficialBody', parent=base['BodyText'], fontSize=9, leading=13,
            textColor=INK, alignment=TA_LEFT),
        'cell': ParagraphStyle('TableCell', parent=base['BodyText'], fontSize=8.5, leading=11),
        'cellhead': ParagraphStyle('TableHead', parent=base['BodyText'], fontName='Helvetica-Bold',
            fontSize=8, leading=10, textColor=colors.white),
        'section': ParagraphStyle('InstructionHead', parent=base['Heading2'], fontName='Helvetica-Bold',
            fontSize=11, leading=14, textColor=INK, spaceBefore=7*mm, spaceAfter=2*mm),
    }


def _person(allocation):
    person = allocation.faculty or allocation.phd_scholar
    if allocation.phd_scholar_id:
        return _phd_chart_label(allocation.phd_scholar), 'PHD'
    designation = allocation.faculty.get_designation_display()
    role = allocation.get_role_type_display()
    label = designation if designation == role else f'{designation} - {role}'
    return (person.name if person else 'Unassigned'), label


def _group_allocations(allocations):
    dates = OrderedDict()
    for allocation in allocations:
        exam = allocation.exam_schedule
        key = (exam.date, exam.start_time, exam.end_time, exam.slot, exam.session_id)
        dates.setdefault(key, OrderedDict()).setdefault(allocation.classroom.name, []).append(allocation)
    return dates


def build_duty_order(allocations, filename='duty_order.pdf', filtered=False):
    styles = _styles()
    title = 'EXAMINATION DUTY ORDER'
    story = [Paragraph(title, styles['title'])]
    exams = OrderedDict()
    for a in allocations:
        exams[a.exam_schedule_id] = a.exam_schedule
    exam_names = list(dict.fromkeys(
        (e.subject.name if e.subject_id else '') for e in exams.values() if e.subject_id
    ))
    exam_label = getattr(settings, 'EXAM_DUTY_EXAMINATION_NAME', '').strip()
    if not exam_label:
        exam_label = ' / '.join(exam_names) if exam_names else 'Examination'
    session_names = list(dict.fromkeys(e.session.name for e in exams.values() if e.session_id))
    month_year = ', '.join(dict.fromkeys(e.date.strftime('%B %Y') for e in exams.values()))
    meta = [escape(exam_label.upper())]
    if session_names:
        meta.append(escape(' | '.join(session_names)))
    if month_year:
        meta.append(escape(month_year))
    ref = getattr(settings, 'EXAM_DUTY_REFERENCE', '').strip()
    issue = timezone.localdate().strftime('%d %B %Y')
    ref_text = f'Ref: {escape(ref)} &nbsp;&nbsp; ' if ref else ''
    story += [Paragraph(' &nbsp; | &nbsp; '.join(meta), styles['meta']),
              Paragraph(f'{ref_text}Issue date: {issue}', styles['meta']), Spacer(1, 3*mm)]
    if not allocations:
        story.append(Paragraph('No finalized duty allocations are available for this selection.', styles['body']))

    for key, rooms in _group_allocations(allocations).items():
        date, start, end, slot, session_id = key
        first = next(iter(next(iter(rooms.values()))))
        exam = first.exam_schedule
        date_line = f'{date.strftime("%A, %d %B %Y")} &nbsp; | &nbsp; {escape(exam.get_slot_display())}'
        if start and end:
            date_line += f' &nbsp; | &nbsp; {start.strftime("%I:%M %p")} - {end.strftime("%I:%M %p")}'
        if exam.reporting_time:
            date_line += f' &nbsp; | &nbsp; Report by {exam.reporting_time.strftime("%I:%M %p")}'
        if exam.subject_id:
            date_line += f' &nbsp; | &nbsp; {escape(exam.subject.name)}'
        if exam.session_id:
            date_line += f' &nbsp; | &nbsp; {escape(exam.session.name)}'
        continuation_label = f'{date.strftime("%A, %d %B %Y")} | {exam.get_slot_display()} | {start:%I:%M %p} - {end:%I:%M %p}'
        story.append(DutySectionMarker(continuation_label))
        story.append(Paragraph(date_line, styles['date']))
        for room_name, room_allocations in rooms.items():
            story.append(Paragraph(f'ROOM NO. {escape(room_name)}', styles['room']))
            data = [[Paragraph('S. No.', styles['cellhead']),
                     Paragraph('Name', styles['cellhead']),
                     Paragraph('Designation / Role', styles['cellhead'])]]
            for idx, allocation in enumerate(room_allocations, 1):
                name, designation = _person(allocation)
                data.append([str(idx), Paragraph(escape(name), styles['cell']),
                             Paragraph(escape(designation), styles['cell'])])
            table = Table(data, colWidths=[17*mm, 82*mm, 71*mm], repeatRows=1, splitByRow=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), ACCENT),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('GRID', (0,0), (-1,-1), .45, RULE),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, PALE]),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (0,1), (0,-1), 'CENTER'),
                ('LEFTPADDING', (0,0), (-1,-1), 7), ('RIGHTPADDING', (0,0), (-1,-1), 7),
                ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ]))
            story.append(table)
        # Instructions are rendered once per schedule, deduplicated below at the end.

    instructions = list(dict.fromkeys(
        line.strip() for exam in exams.values() for line in (exam.instructions or '').splitlines()
        if line.strip()
    ))
    story.append(Paragraph('EXAMINATION INSTRUCTIONS', styles['section']))
    if instructions:
        for idx, line in enumerate(instructions, 1):
            story.append(Paragraph(f'{idx}. {escape(line)}', styles['body']))
    else:
        defaults = [
            'All assigned staff shall report to their allotted rooms before commencement of the examination.',
            'All staff shall perform their assigned examination duties responsibly and follow department instructions.',
            'Any duty replacement must be recorded and approved in ExamDutyManager.',
        ]
        for idx, line in enumerate(defaults, 1):
            story.append(Paragraph(f'{idx}. {escape(line)}', styles['body']))
    story.extend([Spacer(1, 8*mm)])
    signatures = Table([
        ['', '', ''],
        ['Examination Coordinator', '', 'Head of Department (HOD)'],
        ['', '', ''],
        ['', '', 'Department of Computer Science & Engineering'],
    ], colWidths=[58*mm, 58*mm, 58*mm], rowHeights=[8*mm, 6*mm, 6*mm, 6*mm])
    signatures.setStyle(TableStyle([
        ('LINEABOVE', (0,1), (0,1), .7, INK), ('LINEABOVE', (2,1), (2,1), .7, INK),
        ('ALIGN', (0,1), (-1,-1), 'CENTER'), ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8), ('TEXTCOLOR', (0,1), (-1,-1), INK),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
    ]))
    story.append(signatures)
    return _pdf_response(story, filename, title)


def build_individual_slip(allocation):
    styles = _styles()
    exam = allocation.exam_schedule
    name, designation = _person(allocation)
    story = [Paragraph('INDIVIDUAL EXAMINATION DUTY SLIP', styles['title']),
             Paragraph(escape(getattr(settings, 'EXAM_DUTY_EXAMINATION_NAME', '').strip() or
                              (exam.subject.name if exam.subject_id else 'Examination')), styles['meta']),
             Paragraph(f'Issue date: {timezone.localdate():%d %B %Y}', styles['meta']),
             Spacer(1, 8*mm)]
    report = exam.reporting_time.strftime('%I:%M %p') if exam.reporting_time else 'Before examination commencement'
    values = [
        ('Name', name), ('Designation', designation), ('Examination date', exam.date.strftime('%A, %d %B %Y')),
        ('Reporting time', report), ('Examination time', f'{exam.start_time:%I:%M %p} - {exam.end_time:%I:%M %p}'),
        ('Session / Shift', exam.session.name if exam.session_id else exam.get_slot_display()),
        ('Room', allocation.classroom.name), ('Assigned duty role', allocation.get_role_type_display()),
    ]
    data = [[Paragraph(escape(k), styles['cell']), Paragraph(escape(v), styles['cell'])] for k,v in values]
    table = Table(data, colWidths=[48*mm, 130*mm])
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,RULE),('BACKGROUND',(0,0),(0,-1),PALE),
        ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.extend([table, Paragraph('INSTRUCTIONS', styles['section'])])
    instructions = [x.strip() for x in (exam.instructions or '').splitlines() if x.strip()]
    if not instructions:
        instructions = ['Report to the allotted room before commencement and follow all examination instructions issued by the department.']
    story.extend(Paragraph(f'{i}. {escape(line)}', styles['body']) for i,line in enumerate(instructions,1))
    return _pdf_response(story, f'duty-slip-{allocation.pk}.pdf', 'Individual Examination Duty Slip')


def filtered_allocations(date_value='', slot_value='', session_id=''):
    qs = allocation_queryset()
    if date_value:
        qs = qs.filter(exam_schedule__date=date_value)
    if session_id:
        qs = qs.filter(exam_schedule__session_id=session_id)
    if slot_value in (ExamSchedule.Slot.MORNING, ExamSchedule.Slot.EVENING):
        qs = qs.filter(exam_schedule__slot=slot_value)
    return list(qs)


def _month_year(allocations):
    unique = list(dict.fromkeys((a.exam_schedule.date.year, a.exam_schedule.date.month)
                                for a in allocations))
    if not unique:
        return ''
    labels = [f'{datetime_date(year, month, 1).strftime("%B")} {year}' for year, month in unique]
    return ', '.join(labels)


def _chart_groups(allocations):
    groups = OrderedDict()
    for a in allocations:
        key = (a.exam_schedule_id, a.classroom_id)
        groups.setdefault(key, []).append(a)
    return groups.values()


def _chart_person_columns(assignments):
    faculty = []
    designations = []
    scholars = []
    for a in assignments:
        if a.faculty_id:
            faculty.append(a.faculty.name)
            designations.append(a.faculty.get_designation_display())
        if a.phd_scholar_id:
            scholars.append(_phd_chart_label(a.phd_scholar))
    return ([escape(name) for name in faculty] or ['-'],
            [escape(value) for value in designations] or ['-'],
            [escape(value) for value in scholars] or ['-'])


def _phd_chart_label(scholar):
    if scholar.scholar_id:
        return scholar.scholar_id
    name = scholar.name.strip()
    prefix = 'research scholar'
    if name.casefold().startswith(prefix):
        return 'PHD' + name[len(prefix):]
    if name.casefold().startswith('phd'):
        return name
    return f'PHD - {name}' if name else 'PHD'


def _chart_page(canvas, doc):
    canvas.saveState()
    width, height = landscape(A4)
    institute = getattr(settings, 'INSTITUTE_NAME', 'Maulana Azad National Institute of Technology Bhopal')
    department = getattr(settings, 'EXAM_DUTY_DEPARTMENT', 'Department of Computer Science & Engineering')
    canvas.setFillColor(INK)
    canvas.setFont('Helvetica-Bold', 13)
    canvas.drawCentredString(width / 2, height - 14 * mm, institute.upper())
    canvas.setFont('Helvetica-Bold', 9)
    canvas.drawCentredString(width / 2, height - 20 * mm, department.upper())
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(.7)
    canvas.line(doc.leftMargin, height - 24 * mm, width - doc.rightMargin, height - 24 * mm)
    canvas.setFont('Helvetica-Bold', 11)
    canvas.drawCentredString(width / 2, height - 31 * mm, doc.chart_title)
    if doc.page == 1:
        canvas.setFont('Helvetica', 8.5)
        canvas.drawRightString(width - doc.rightMargin, height - 37 * mm,
                               f'Issue date: {timezone.localdate():%d/%m/%Y}')
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(.45)
    canvas.line(doc.leftMargin, 13 * mm, width - doc.rightMargin, 13 * mm)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#52606d'))
    canvas.drawRightString(width - doc.rightMargin, 9 * mm, f'Page {doc.page}')
    canvas.restoreState()


def build_duty_chart(allocations, examination_type, filename, inline=False):
    """Render a compact official chart with one row per exam schedule and room."""
    allocations = list(allocations)
    type_label = dict(ExamSchedule.ExaminationType.choices).get(examination_type,
                                                                 'Examination')
    title = f'B.Tech. {type_label} Duty Chart'
    period = _month_year(allocations)
    if period:
        title += f', {period}'
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('ChartCell', parent=styles['BodyText'], fontName='Helvetica',
                          fontSize=7.5, leading=8.5, textColor=INK, spaceAfter=0)
    header = ParagraphStyle('ChartHeader', parent=cell, fontName='Helvetica-Bold',
                            fontSize=7.5, leading=8.5, textColor=colors.white)
    story = []
    coordinator_duties = {a.exam_schedule_id: a for a in allocations if a.is_subject_coordinator}
    rows = [[Paragraph(text, header) for text in
             ('Date', 'Time', 'Subject', 'Room No.', 'Faculty / Invigilator', 'Designation', 'Subject Coordinator', 'PhD Scholars')]]
    for assignments in _chart_groups(allocations):
        exam = assignments[0].exam_schedule
        faculty, designations, scholars = _chart_person_columns(assignments)
        coordinator_assignment = coordinator_duties.get(exam.pk)
        if not exam.subject_id:
            coordinator_text = 'No subject coordinator required'
        elif not exam.subject.coordinator_id:
            coordinator_text = 'UNRESOLVED: no coordinator configured'
        elif coordinator_assignment and coordinator_assignment.faculty_id == exam.subject.coordinator_id:
            coordinator_text = f'{exam.subject.coordinator.name} (duty: {coordinator_assignment.classroom.name})'
        else:
            coordinator_text = f'{exam.subject.coordinator.name} - UNRESOLVED: duty not assigned'
        chunks = max((len(faculty) + 7) // 8, (len(designations) + 7) // 8,
                     (len(scholars) + 9) // 10, 1)
        for index in range(chunks):
            faculty_text = '<br/>'.join(faculty[index*8:(index+1)*8])
            designation_text = '<br/>'.join(designations[index*8:(index+1)*8])
            scholar_text = '<br/>'.join(scholars[index*10:(index+1)*10])
            rows.append([
                Paragraph(exam.date.strftime('%d/%m/%Y'), cell),
                Paragraph(f'{exam.start_time:%I:%M %p} - {exam.end_time:%I:%M %p}', cell),
                Paragraph(escape(exam.subject.name if exam.subject_id else '-'), cell),
                Paragraph(escape(assignments[0].classroom.name), cell),
                Paragraph(faculty_text or '-', cell), Paragraph(designation_text or '-', cell),
                Paragraph(escape(coordinator_text), cell), Paragraph(scholar_text or '-', cell),
            ])
    is_empty = len(rows) == 1
    if is_empty:
        rows.append([Paragraph('No finalized assignments for this examination type.', cell)] + [''] * 7)
    table = LongTable(rows, colWidths=[19*mm, 27*mm, 40*mm, 25*mm, 29*mm, 34*mm, 43*mm, 50*mm],
                      repeatRows=1, splitByRow=1, hAlign='LEFT')
    table_commands = [
        ('BACKGROUND', (0, 0), (-1, 0), INK),
        ('GRID', (0, 0), (-1, -1), .5, RULE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PALE]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 1), (3, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]
    if is_empty:
        table_commands.extend([('SPAN', (0, 1), (-1, 1)), ('ALIGN', (0, 1), (-1, 1), 'CENTER')])
    table.setStyle(TableStyle(table_commands))
    story.append(table)

    notes = list(dict.fromkeys(line.strip() for a in allocations
                               for line in (a.exam_schedule.instructions or '').splitlines()
                               if line.strip()))
    if not notes:
        notes = [getattr(settings, 'EXAM_DUTY_DEFAULT_NOTE', '').strip() or
                 'All faculty members and PhD scholars are requested to report to their allotted rooms before the commencement of the examination.']
    story += [Spacer(1, 4*mm), Paragraph('Notes:', ParagraphStyle(
        'ChartNotesTitle', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=9,
        leading=11, textColor=INK, spaceAfter=1*mm))]
    story.extend(Paragraph(escape(note), ParagraphStyle('ChartNote', parent=cell, fontSize=8.5,
                                                        leading=10.5)) for note in notes)
    story += [Spacer(1, 2*mm)]
    signature = Table([['Exam Coordinator(s)', '(HOD CSE)'], ['', 'Department of Computer Science & Engineering']],
                      colWidths=[120*mm, 120*mm], rowHeights=[10*mm, 4*mm])
    signature.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (0, 0), .7, INK), ('LINEABOVE', (1, 0), (1, 0), .7, INK),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
    ]))
    story.append(signature)

    output = BytesIO()
    page_size = landscape(A4)
    doc = BaseDocTemplate(output, pagesize=page_size, leftMargin=13*mm, rightMargin=13*mm,
                          topMargin=42*mm, bottomMargin=20*mm, title=title,
                          author=getattr(settings, 'INSTITUTE_NAME', ''))
    doc.chart_title = title
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='chart')
    doc.addPageTemplates(PageTemplate(id='official-chart', frames=frame, onPage=_chart_page))
    doc.build(story)
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response


def build_faculty_details(faculty, allocations, filename='faculty-duty-details.pdf', inline=False):
    allocations = list(allocations)
    title = 'Individual Faculty Duty Details'
    styles = getSampleStyleSheet()
    detail = ParagraphStyle('FacultyDetails', parent=styles['BodyText'], fontSize=9,
                            leading=13, textColor=INK)
    cell = ParagraphStyle('FacultyDutyCell', parent=detail, fontSize=8.5, leading=10)
    header = ParagraphStyle('FacultyDutyHeader', parent=cell, fontName='Helvetica-Bold',
                            textColor=colors.white)
    story = [Paragraph(f'<b>{escape(faculty.name)}</b> - {escape(faculty.get_designation_display())}', detail),
             Spacer(1, 4*mm)]
    rows = [[Paragraph(label, header) for label in ('Date', 'Time', 'Room No.', 'Duty Role')]]
    for allocation in allocations:
        exam = allocation.exam_schedule
        rows.append([Paragraph(exam.date.strftime('%d/%m/%Y'), cell),
                     Paragraph(f'{exam.start_time:%I:%M %p} - {exam.end_time:%I:%M %p}', cell),
                     Paragraph(escape(allocation.classroom.name), cell),
                     Paragraph(escape(allocation.get_role_type_display()), cell)])
    if len(rows) == 1:
        rows.append([Paragraph('No current duties assigned.', cell), '', '', ''])
    table = LongTable(rows, colWidths=[35*mm, 48*mm, 40*mm, 145*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),INK), ('GRID',(0,0),(-1,-1),.5,RULE),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
    ]))
    story.append(table)
    output = BytesIO()
    doc = BaseDocTemplate(output, pagesize=landscape(A4), leftMargin=13*mm, rightMargin=13*mm,
                          topMargin=42*mm, bottomMargin=20*mm, title=title)
    doc.chart_title = title
    doc.addPageTemplates(PageTemplate(id='faculty-details',
        frames=Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='faculty'),
        onPage=_chart_page))
    doc.build(story)
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'{"inline" if inline else "attachment"}; filename="{filename}"'
    return response
