# Legacy texture conversion startup message

## Scope

A user screenshot shows `mimi.texhashbind_select_file` and two reports of
`Texture format conversion could not start; see the console for details`.
This is a legacy MIMIBlender operator path, not an MMT desktop failure.
The user's DDS and full console traceback were not supplied; a filename alone
cannot establish whether that particular file is valid or matches its capture.

## Confirmed historical false error

Before commit `f6bfe1e`, the conversion button in
[texture_format_widgets.py](../blueprint/texture_format_widgets.py) called
`texture_format_service.start_conversion(jobs)` and treated a return value of
zero as an error whenever no batch was running.

[The planner](../texcomb/core/dds_match.py) deliberately returns no plan for a
validated DDS with matching storage, dimensions and mip policy. The runner
therefore returns zero: there is no worker to start, and direct byte copying is
the correct result. The old button confused this successful no-op with a failed
planning pass. It also used the same generic message for genuinely unsupported
or damaged inputs, so the screenshot's text cannot distinguish those cases.

## Existing fix and current workflow

Commit `f6bfe1e` removed the manual conversion operators and moved conversion
ownership into Generate Mod. The current
[file chooser](../blueprint/texture_row_ui.py) only validates the selected path
and assigns it to the correct row. It does not launch conversion.

The current [export operator](../ui/ui_func_export.py) skips the conversion phase
when there is no pending plan, while the final texture writer validates and
copies matching DDS bytes. Necessary conversions still use the bundled texconv.
The original capture is never rewritten to make the replacement appear valid.

The published MIMIBlender 1.0.78 package is available at
[the release page](https://github.com/StarBobis/MIMIBlender/releases/tag/v1.0.78).
Update the Blender add-on, close every Blender instance and restart before
opening the saved blueprint. Updating MMT alone does not reload add-on code.
Select the replacement file and use Generate Mod; a matching DDS needs no
separate Convert action. Old node labels are supported by title migration.

If an old operator name or the old manual-conversion button still appears after
updating, the running Blender session is still using the legacy add-on path.
Check the enabled add-on version and installed package location before changing
any texture bytes. Do not delete the Mod, cache, or source DDS as a first remedy.

## Regression added for this report

[Global Hash Blender tests](../tools/test_global_hash_blender.py) now include
`test_matching_dds_is_a_successful_noop_not_a_startup_failure`:

- register the real add-on and generate an authoritative DDS with bundled texconv;
- select a matching replacement through the real Blender file-picker operator,
  including a non-ASCII folder and spaces;
- require no conversion plan, zero started jobs, a finished error-free outcome,
  and no external-tool call on the matching path;
- inspect the actual Hash texture writer's output and compare source, original
  and exported bytes;
- truncate the replacement and require a real planning error and refused output,
  preserving the previously exported texture.

Run:

```text
D:\Softs\Blender4.5LTS\blender.exe --background --factory-startup --python-exit-code 1 --python tools/test_global_hash_blender.py
D:\Softs\Blender4.5LTS\blender.exe --background --factory-startup --python-exit-code 1 --python tools/test_texture_format_blender.py
```

Validation on Blender 4.5.3: all 14 Global Hash tests passed, including the
matching-DDS no-op and truncated-DDS negative. The separate real conversion
suite also passed its registered-node, bundled-tool, output-header and cache
checks. This is export/byte validation, not an in-game visual comparison or a
validation of the unavailable user's DDS.

This report does not reinstate the removed conversion button. Current runtime
code already contains the historical fix; the new change adds regression and
support documentation. If Generate Mod still reports a conversion failure in
1.0.78, request the first full console exception, Blender/add-on versions and
the source/captured DDS metadata. Check tool absence, invalid format, truncated
payload and filesystem failures separately; do not label every zero-job result
as success or every DDS failure as a missing tool.
