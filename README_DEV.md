# Blender Download URLs
- https://download.blender.org/release/

# Change Log
This project supports Blender 5.2 LTS as its only supported version; APIs of older versions are out of scope.
- https://docs.blender.org/api/5.2/change_log.html

# Blender API Manual
- https://www.blender.org/support/
- https://docs.blender.org/api/5.2/

# Essential Development Add-ons
- https://github.com/JacquesLucke/blender_vscode              (Recommended, first choice)
- https://github.com/BlackStartx/PyCharm-Blender-Plugin       (Works too, but not recommended)

# Caching Issues in Blender Add-on Development

When developing a Blender add-on with VSCode, a symbolic link pointing to the project is created, at roughly the following path:

C:\Users\Administrator\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons

When the add-on architecture changes drastically, Blender may fail to start; in that case, you need to manually delete the add-on's cached symbolic link.

In other words, relocating the add-on can cause the following error:

```
Traceback (most recent call last):
  File "c:\Users\Administrator\.vscode\extensions\jacqueslucke.blender-development-0.0.30\pythonFiles\launch.py", line 28, in <module>
    blender_vscode.startup(
  File "c:\Users\Administrator\.vscode\extensions\jacqueslucke.blender-development-0.0.30\pythonFiles\include\blender_vscode\__init__.py", line 31, in startup
    path_mappings = load_addons.setup_addon_links(addons_to_load)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Administrator\.vscode\extensions\jacqueslucke.blender-development-0.0.30\pythonFiles\include\blender_vscode\load_addons.py", line 40, in setup_addon_links
    load_path = _link_addon_or_extension(addon_info)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Administrator\.vscode\extensions\jacqueslucke.blender-development-0.0.30\pythonFiles\include\blender_vscode\load_addons.py", line 64, in _link_addon_or_extension
    create_link_in_user_addon_directory(addon_info.load_dir, load_path)
  File "c:\Users\Administrator\.vscode\extensions\jacqueslucke.blender-development-0.0.30\pythonFiles\include\blender_vscode\load_addons.py", line 237, in create_link_in_user_addon_directory
    _winapi.CreateJunction(str(directory), str(link_path))
FileExistsError: [WinError 183] Cannot create a file when that file already exists.
```

If this error appears, delete the symbolic link at that location, then press Ctrl + Shift + P again and the project can be debugged normally.

# Folder and File Name Case Sensitivity

All folders must be lowercase, because git cannot track case-only renames of folder names; at least the git integrated in VSCode cannot, and it may also be a VSCode issue.

File names must also be lowercase, because Github also cannot track case-only renames of file names.



# Known Issues

- For Blender add-on development, the wrapping of Blender's bpy part should be done at a relatively low level of the data structures; otherwise the code becomes messy and the underlying principles become impossible to understand, which is exactly the situation we are currently facing. Some utility classes must be dedicated to interfacing with the types in bpy.


# Non-Mirroring Workflow Issue
On import, set the X component of Scale to -1 and apply it so that the model is not mirrored.
On export, set the X component of Scale to -1 again and apply it so that the model is mirrored back.
This avoids operating on the underlying data structures; it is very elegant, and this is basically how it should be done from now on.

So for now, delete all the old non-mirroring workflow code and wait for later testing.
