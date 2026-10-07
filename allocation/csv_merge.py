"""Safe, testable CSV seating-export helpers."""
import csv
import io


FORMULA_PREFIXES = ('=', '+', '-', '@')


def safe_csv_value(value):
    value = '' if value is None else str(value)
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def merge_seating_csv(source, seating_by_roll):
    """Append seating columns without changing the input's original column order."""
    reader = csv.DictReader(source)
    if not reader.fieldnames or 'roll_no' not in reader.fieldnames:
        raise ValueError('CSV must include a roll_no column.')
    fieldnames = list(reader.fieldnames)
    additions = ['room_name', 'row', 'column', 'seat_no']
    for field in additions:
        if field in fieldnames:
            raise ValueError(f'CSV already contains {field}.')

    result = io.StringIO(newline='')
    writer = csv.DictWriter(result, fieldnames=fieldnames + additions)
    writer.writeheader()
    unallotted = []
    for row in reader:
        roll_no = row.get('roll_no', '').strip()
        section = row.get('section', '').strip()
        seating = seating_by_roll.get((section, roll_no)) if section else None
        if seating is None:
            seating = seating_by_roll.get(roll_no)
        if seating is None:
            unallotted.append(roll_no)
            seating = {}
        output = {field: safe_csv_value(row.get(field, '')) for field in fieldnames}
        output.update({field: safe_csv_value(seating.get(field, '')) for field in additions})
        writer.writerow(output)
    return result.getvalue(), unallotted
