"""Validate the assembled WWMI INI before replacing a working mod.

3Dmigoto names are case insensitive. Never silently merge executable sections
or conflicting globals. Identical resource declarations can safely be shared
by several explicit texture bindings, but different declarations must fail.
"""
import hashlib
import re
from pathlib import Path


def disable_legacy_ini_files(folder, mod_name, scopes):
    """Disable only unchanged, generator-owned per-DrawIB INIs.

    User-edited files are never removed or renamed. Their stored checksum
    cannot prove ownership after editing, so stop with an actionable message.
    Verify every absolute source/destination before renaming a legacy file.
    """
    directory = Path(folder).resolve()
    # Removed blueprint scopes may still have old active INIs in this folder.
    # Include their exact mod-name prefix too; the ownership checks below
    # refuse unrelated or edited files instead of silently loading conflicts.
    prefix = mod_name + '_'
    scopes = set(scopes)
    for candidate in directory.glob('*.ini'):
        if candidate.stem.startswith(prefix):
            scopes.add(candidate.stem[len(prefix):])
    pending = []
    # Preflight every candidate before changing any file, so one edited INI
    # cannot leave a half-migrated collection. Existing backups stay intact.
    for scope in sorted(set(scopes)):
        source = (directory / (mod_name + "_" + scope + ".ini")).resolve()
        destination = source.with_suffix(".ini.disabled")
        if source.parent != directory or destination.parent != directory:
            raise ValueError("WWMI legacy INI path escapes mod directory")
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        marker = re.search(r"\n;sha256=([0-9a-f]{64})\s*$", text)
        # The builder hashes all rendered lines before appending this marker.
        # Section/runtime checks keep unrelated INIs outside migration scope.
        owned = marker and hashlib.sha256(text[:marker.start()].encode("utf-8")).hexdigest() == marker.group(1)
        owned = owned and "[ResourcePositionBuffer_" + scope + "]" in text and "WWMIv1" in text
        if not owned:
            raise ValueError("WWMI legacy INI is edited or unrecognized; move it out of the mod directory before exporting: " + str(source))
        number = 1
        while destination.exists():
            destination = source.with_suffix('.ini.disabled.' + str(number))
            number += 1
        pending.append((source, destination))
    for source, destination in pending:
        source.rename(destination)



def validate_ini_builder(builder):
    """Check names and remove only identical repeated resource declarations.

    M_IniSection may contain several literal headers, so validation must inspect
    the actual lines rather than SectionName alone. Constants/Present have
    already been assembled by M_IniBuilder in their original contribution order.
    """
    blocks = []
    for section in builder.ini_section_list:
        if section.SectionName:
            blocks.append([section, "[" + section.SectionName + "]", []])
        for line in section.SectionLineList:
            if re.fullmatch(r"\s*\[[^\]\r\n]+\]\s*", line):
                blocks.append([section, line, []])
            elif blocks:
                blocks[-1][2].append(line)

    sections = {}
    variables = set()
    retained = []
    for section, header, lines in blocks:
        name = header.strip()[1:-1].casefold()
        # Compare active resource settings, ignoring formatting and comments.
        # Do not case-fold filenames or data: their values can be significant.
        settings = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith(";")]
        if name in sections:
            if name.startswith("resource") and sections[name] == settings:
                continue
            raise ValueError("WWMI INI duplicate section: " + header)
        sections[name] = settings
        retained.append((section, header, lines))
        for line in lines:
            declaration = re.match(r"\s*global(?:\s+persist)?\s+(\$[^\s=]+)", line, re.IGNORECASE)
            if declaration:
                variable = declaration.group(1).casefold()
                if variable in variables:
                    raise ValueError("WWMI INI duplicate global: " + variable)
                variables.add(variable)

    # References to generated commands/resources must resolve locally.
    # Runtime API names contain a namespace separator and remain external.
    # Validate command targets even inside conditional or post statements.
    for _section, _header, lines in retained:
        for line in lines:
            active = line.split(";", 1)[0]
            for target in re.findall(r"(?:=\s*|\b(?:ref|copy)\s+)((?:CommandList|CustomShader|Resource)[\w.\\-]+)", active, re.IGNORECASE):
                if "\\" not in target and target.casefold() not in sections:
                    raise ValueError("WWMI INI unresolved section reference: " + target)

    # Rebuild literal blocks without changing their order or command bodies.
    # Singleton headers stay in SectionName and must not be emitted twice.
    for section in builder.ini_section_list:
        section.SectionLineList = []
    for section, header, lines in retained:
        if not section.SectionName:
            section.SectionLineList.append(header)
        section.SectionLineList.extend(lines)
