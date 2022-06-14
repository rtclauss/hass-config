'''Miscellaneous support functions for watchman'''
import glob
import re

def get_next_file(folder_list, excluded_folders, ignored_files, logger):
    '''Returns next file for scan'''
    if not ignored_files:
        ignored_files = ""
    ignored_files_re = re.compile(ignored_files)
    for folder in folder_list:
        for filename in glob.iglob(folder, recursive=True):
            yield (filename, (ignored_files and ignored_files_re.match(filename)))

def add_entry(_list, entry, yaml_file, lineno):
    '''Add entry to list of missing entities with line number information'''
    if entry in _list:
        if yaml_file in _list[entry]:
            _list[entry].get(yaml_file, []).append(lineno)
    else:
        _list[entry] = {yaml_file: [lineno]}

def parse(folders, excluded_folders, ignored_files, logger=None):
    '''Parse a yaml or json file for entities/services'''
    if logger:
        logger.log(f"::parse:: ignored_files={ignored_files}")
    files_parsed = 0
    entity_pattern = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=\")|(?<=\'))([A-Za-z_0-9]*\s*:)?(?:\s*)?"
    r"((air_quality|alarm_control_panel|alert|automation|binary_sensor|button|calendar|camera|"
    r"climate|counter|device_tracker|fan|group|humidifier|input_boolean|input_datetime|"
    r"input_number|input_select|light|lock|media_player|number|person|plant|proximity|remote|"
    r"scene|script|select|sensor|sun|switch|timer|vacuum|weather|zone)\.[A-Za-z_*0-9]+)")
    service_pattern = re.compile(r"service:\s*([A-Za-z_0-9]*\.[A-Za-z_0-9]+)")
    comment_pattern = re.compile(r'#.*')
    entity_list = {}
    service_list = {}
    effectively_ignored = []
    for yaml_file, ignored in get_next_file(folders, excluded_folders, ignored_files, logger):
        if ignored:
            effectively_ignored.append(yaml_file)
            continue
        files_parsed += 1
        for i, line in enumerate(open(yaml_file, encoding='utf-8')):
            line = re.sub(comment_pattern, '', line)
            for match in re.finditer(entity_pattern, line):
                typ, val = match.group(1), match.group(2)
                if typ != "service:" and "*" not in val and not val.endswith('.yaml'):
                    add_entry(entity_list, val, yaml_file, i+1)
            for match in re.finditer(service_pattern, line):
                val = match.group(1)
                add_entry(service_list, val, yaml_file, i+1)
    if logger:
        logger.log(f"::parse:: Parsed files: {files_parsed} ")
        logger.log(f"::parse:: Ignored files: {effectively_ignored}")
    return (entity_list, service_list, files_parsed, len(effectively_ignored))
