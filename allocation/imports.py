"""Safe parsing and row-wise validation for administrator data imports."""
import csv
import posixpath
import zipfile
from io import BytesIO, StringIO
from xml.etree import ElementTree


IMPORT_SCHEMAS = {
    'subjects': {'required': ['name'], 'optional': ['coordinator_email', 'coordinator_employee_id']},
    'faculty': {'required': ['name', 'designation', 'email'], 'optional': ['employee_id', 'department', 'contact', 'duty_quota']},
    'phd': {'required': ['name', 'email'], 'optional': ['scholar_id', 'department', 'academic_year', 'contact', 'duty_quota']},
    'students': {'required': ['roll_no', 'section'], 'optional': ['name', 'category', 'subjects']},
    'classrooms': {'required': ['name', 'rows', 'columns'], 'optional': []},
    'sections': {'required': ['name'], 'optional': ['department']},
    'faculty_timetable': {'required': ['employee_id', 'weekday', 'start_time', 'end_time'], 'optional': ['label']},
    'phd_timetable': {'required': ['scholar_id', 'weekday', 'start_time', 'end_time'], 'optional': ['label']},
    'minor_registrations': {'required': ['roll_no', 'section', 'subject'], 'optional': []},
    'elective_registrations': {'required': ['roll_no', 'section', 'subject'], 'optional': []},
}


def read_tabular_upload(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValueError('Upload a file no larger than 5 MB.')
    name = upload.name.lower()
    if name.endswith('.csv'):
        text = upload.read().decode('utf-8-sig')
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames:
            raise ValueError('The CSV file needs a header row.')
        return [{str(k or '').strip().lower(): str(v or '').strip() for k, v in row.items()} for row in reader]
    if name.endswith('.xlsx'):
        data = upload.read()
        try:
            from openpyxl import load_workbook
        except ImportError:
            return _read_xlsx_standard_library(data)
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            raise ValueError('The Excel file needs a header row.')
        keys = [str(value or '').strip().lower() for value in header]
        result = [{keys[i]: str(value or '').strip() for i, value in enumerate(row) if i < len(keys)} for row in rows]
        workbook.close()
        return result
    raise ValueError('Choose a .csv or .xlsx file.')


def _read_xlsx_standard_library(data):
    """Read the first worksheet's scalar values from an OOXML workbook."""
    ns = {
        'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'rel': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'pkg': 'http://schemas.openxmlformats.org/package/2006/relationships',
    }
    try:
        with zipfile.ZipFile(BytesIO(data)) as workbook:
            book = ElementTree.fromstring(workbook.read('xl/workbook.xml'))
            sheet = book.find('main:sheets/main:sheet', ns)
            if sheet is None:
                raise ValueError('The Excel workbook has no worksheets.')
            relationship_id = sheet.attrib.get(f"{{{ns['rel']}}}id")
            relations = ElementTree.fromstring(workbook.read('xl/_rels/workbook.xml.rels'))
            relation = next((r for r in relations.findall('pkg:Relationship', ns)
                             if r.attrib.get('Id') == relationship_id), None)
            if relation is None:
                raise ValueError('The first worksheet could not be located.')
            target = relation.attrib['Target'].lstrip('/')
            sheet_path = target if target.startswith('xl/') else posixpath.normpath(posixpath.join('xl', target))
            shared = []
            if 'xl/sharedStrings.xml' in workbook.namelist():
                strings_root = ElementTree.fromstring(workbook.read('xl/sharedStrings.xml'))
                shared = [''.join(part.text or '' for part in item.findall('.//main:t', ns))
                          for item in strings_root.findall('main:si', ns)]
            worksheet = ElementTree.fromstring(workbook.read(sheet_path))
            parsed_rows = []
            for row in worksheet.findall('.//main:sheetData/main:row', ns):
                cells = {}
                for cell in row.findall('main:c', ns):
                    reference = cell.attrib.get('r', '')
                    col = ''.join(char for char in reference if char.isalpha())
                    if not col:
                        continue
                    cell_type = cell.attrib.get('t')
                    if cell_type == 'inlineStr':
                        value = ''.join(part.text or '' for part in cell.findall('.//main:t', ns))
                    else:
                        value_node = cell.find('main:v', ns)
                        value = value_node.text if value_node is not None else ''
                        if cell_type == 's' and value:
                            value = shared[int(value)]
                        elif cell_type == 'b' and value:
                            value = 'TRUE' if value == '1' else 'FALSE'
                        elif value:
                            try:
                                number = float(value)
                                value = str(int(number)) if number.is_integer() else str(number)
                            except ValueError:
                                pass
                    cells[col] = str(value or '').strip()
                parsed_rows.append(cells)
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, IndexError) as exc:
        raise ValueError('The Excel workbook is invalid or unreadable.') from exc
    if not parsed_rows:
        raise ValueError('The Excel file needs a header row.')
    columns = sorted({col for row in parsed_rows for col in row}, key=lambda col: (len(col), col))
    headers = [parsed_rows[0].get(col, '').strip().lower() for col in columns]
    if not any(headers):
        raise ValueError('The Excel file needs a header row.')
    result = []
    for row in parsed_rows[1:]:
        converted = {}
        for index, col in enumerate(columns):
            header = headers[index]
            value = row.get(col, '')
            if header in ('start_time', 'end_time', 'reporting_time') and value:
                try:
                    fraction = float(value)
                    if 0 <= fraction < 1:
                        seconds = round(fraction * 24 * 60 * 60) % (24 * 60 * 60)
                        value = f'{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}'
                except ValueError:
                    pass
            if header:
                converted[header] = value
        result.append(converted)
    return result


def validate_import_rows(import_type, rows):
    schema = IMPORT_SCHEMAS[import_type]
    if not rows:
        raise ValueError('The file contains no data rows.')
    missing = sorted(set(schema['required']) - set(rows[0]))
    if missing:
        raise ValueError('Missing required columns: ' + ', '.join(missing))
    result = []
    seen = set()
    duplicate_keys = {
        'subjects': ('name',), 'faculty': ('employee_id',), 'phd': ('scholar_id',),
        'students': ('section', 'roll_no'), 'classrooms': ('name',), 'sections': ('name',),
        'faculty_timetable': ('employee_id', 'weekday', 'start_time', 'end_time'),
        'phd_timetable': ('scholar_id', 'weekday', 'start_time', 'end_time'),
        'minor_registrations': ('roll_no', 'section', 'subject'),
        'elective_registrations': ('roll_no', 'section', 'subject'),
    }[import_type]
    for line, source in enumerate(rows, start=2):
        row = {key: source.get(key, '') for key in schema['required'] + schema['optional']}
        errors = []
        for field in schema['required']:
            if not row.get(field):
                errors.append(f'{field} is required')
        try:
            if import_type == 'students' or import_type.endswith('_registrations'):
                value = int(row.get('roll_no', ''))
                if value < 1: raise ValueError
                row['roll_no'] = value
            if import_type == 'classrooms':
                for key in ('rows', 'columns'):
                    row[key] = int(row[key])
                    if row[key] < 1: raise ValueError
            if import_type in ('faculty', 'phd') and row.get('duty_quota'):
                row['duty_quota'] = int(row['duty_quota'])
                if row['duty_quota'] < 1: raise ValueError
            if import_type == 'faculty' and row.get('designation') not in ('PROF', 'ASSOC', 'ASSIST'):
                errors.append('designation must be PROF, ASSOC, or ASSIST')
            if import_type in ('faculty', 'phd'):
                from django.core.validators import validate_email
                try:
                    validate_email(row['email'])
                except Exception:
                    errors.append('email must be a valid address')
            if import_type in ('faculty_timetable', 'phd_timetable'):
                from datetime import time
                row['weekday'] = int(row['weekday'])
                if row['weekday'] < 0 or row['weekday'] > 6: raise ValueError
                start_time = time.fromisoformat(row['start_time'])
                end_time = time.fromisoformat(row['end_time'])
                if start_time >= end_time:
                    errors.append('end_time must be after start_time')
                row['start_time'], row['end_time'] = start_time.isoformat(), end_time.isoformat()
        except (ValueError, TypeError):
            errors.append('One or more fields have an invalid data type or value')
        category = row.get('category', 'REGULAR').upper() or 'REGULAR'
        if import_type == 'students' and category not in ('REGULAR', 'MINOR', 'ELECTIVE'):
            errors.append('category must be REGULAR, MINOR, or ELECTIVE')
        row['category'] = category
        row_keys = duplicate_keys
        if import_type == 'faculty' and not row.get('employee_id'):
            row_keys = ('email',)
        elif import_type == 'phd' and not row.get('scholar_id'):
            row_keys = ('email',)
        if import_type == 'subjects':
            from .models import Faculty
            email, employee_id = row.get('coordinator_email', '').strip(), row.get('coordinator_employee_id', '').strip()
            by_email = Faculty.objects.filter(email__iexact=email) if email else None
            by_id = Faculty.objects.filter(employee_id__iexact=employee_id) if employee_id else None
            if by_email is not None and by_email.count() != 1:
                errors.append('coordinator_email must match exactly one existing faculty member')
            if by_id is not None and by_id.count() != 1:
                errors.append('coordinator_employee_id must match exactly one existing faculty member')
            if by_email is not None and by_id is not None and by_email.count() == by_id.count() == 1 and by_email.first().pk != by_id.first().pk:
                errors.append('coordinator_email and coordinator_employee_id identify different faculty members')
        values = tuple(str(row.get(field, '')).strip().casefold() for field in row_keys)
        if all(values) and values in seen:
            errors.append('duplicate row in this file')
        seen.add(values)
        result.append({'line': line, 'data': row, 'errors': errors})
    return result
