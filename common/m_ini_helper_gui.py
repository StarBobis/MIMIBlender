
import os
import shutil

from .m_ini_builder import *
from .m_key import M_Key
from ..model.draw_call_model import DrawCallModel
from .global_config import GlobalConfig
from .global_properties import GlobalProperties

class M_IniHelperGUI:
    @staticmethod
    def copy_files(src_dir, dst_dir):
        """
        复制 src_dir 目录下的所有文件（不包括子目录）到 dst_dir 目录
        :param src_dir: 源目录路径
        :param dst_dir: 目标目录路径
        """
        print("[TRACE] M_IniHelperGUI.copy_files() 入口")
        print("[TRACE]   src_dir: " + src_dir)
        print("[TRACE]   dst_dir: " + dst_dir)
        print("[TRACE]   src_dir 存在: " + str(os.path.exists(src_dir)))

        # 确保目标目录存在
        os.makedirs(dst_dir, exist_ok=True)
        print("[TRACE]   dst_dir 已确保存在")

        copied_count = 0
        skipped_not_file = 0

        # 遍历源目录下的所有文件
        files_in_src = os.listdir(src_dir) if os.path.exists(src_dir) else []
        print("[TRACE]   src_dir 内文件/目录列表(" + str(len(files_in_src)) + "个): " + str(files_in_src))

        for filename in files_in_src:
            src_file = os.path.join(src_dir, filename)
            dst_file = os.path.join(dst_dir, filename)

            # 只复制文件，忽略子目录
            if os.path.isfile(src_file):
                print("[TRACE] >>> 复制资源文件: " + src_file + " -> " + dst_file)
                try:
                    shutil.copy2(src_file, dst_file)  # 使用 copy2 保留元数据
                    print("[TRACE] <<< 复制成功: " + dst_file)
                    copied_count += 1
                except Exception as e:
                    print("[TRACE] <<< 复制失败! 异常: " + str(e))
            else:
                print("[TRACE]   跳过非文件: " + src_file)
                skipped_not_file += 1

        print("[TRACE] M_IniHelperGUI.copy_files() 汇总: 复制=" + str(copied_count) + ", 跳过非文件=" + str(skipped_not_file))
                
    @staticmethod
    def copy_res_to_mod_folder():
        '''将插件 resources/ 目录下的所有文件复制到生成 Mod 的 res/ 目录下。'''
        res_path = os.path.join(GlobalConfig.path_generate_mod_folder(), "res")
        os.makedirs(res_path, exist_ok=True)

        addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res_source_path = os.path.join(addon_root, "resources")
        M_IniHelperGUI.copy_files(res_source_path, res_path)

    @staticmethod
    def add_branch_mod_gui_section(ini_builder:M_IniBuilder,key_name_mkey_dict:dict[str,M_Key]):
        '''
        声明模板化GUI面板

        此功能灵感来源于：https://www.caimogu.cc/post/2069456.html
        特别感谢：タ小言
        ; UI Block
        ; By: Comilarex
        ; Modifier: 夕小言

        特别感谢：SinsOfSeven
        '''

        if not GlobalProperties.generate_branch_mod_gui():
            return

        M_IniHelperGUI.copy_res_to_mod_folder()

        if len(key_name_mkey_dict.keys()) == 0:
            return
        
        
        constants_section = M_IniSection(M_SectionType.Constants)
        constants_section.SectionName = "Constants"

        constants_section.append("global $window_width = 1920")
        constants_section.append("global $window_height = 1080")
        constants_section.new_line()

        constants_section.append("global $menu = 0")
        constants_section.append("global $gap = 0.0025")
        constants_section.append("global $mouse_clicked = 0")
        constants_section.append("global $x_size = 0")
        constants_section.append("global $y_size = 0")
        constants_section.new_line()
        
        constants_section.append("global $x_size_Button = 0.03")
        constants_section.append("global $y_size_Button = 0.03")
        constants_section.append("global $Button_frame_pad = 0.002")
        constants_section.append("global $Button_outer_x = 0")
        constants_section.append("global $Button_outer_y = 0")
        constants_section.append("global $y_offset_button = 0.029")
        constants_section.append("global $last_mx = 0")
        constants_section.append("global $last_my = 0")
        constants_section.append("global $mx = 0")
        constants_section.append("global $my = 0")
        constants_section.append("global $x_off_off = 0")
        constants_section.append("global $y_off_off = 0")
        constants_section.append("global $mouse_hold = 0")
        constants_section.append("global persist $final_x_off = -1")
        constants_section.append("global persist $final_y_off = 0.05845")
        constants_section.append("global $is_dragging = 0")
        constants_section.append("global $drag_start_x = 0")
        constants_section.append("global $drag_start_y = 0")
        constants_section.append("global $new_x_off = 0")
        constants_section.append("global $new_y_off = 0")
        constants_section.append("global $total_y_size = 0")
        constants_section.append("global $y_Title_size = 0.045")
        constants_section.append("global $x_Title_size = 0.12")
        constants_section.append("global $y_Credit_size = 0.03")
        constants_section.append("global $x_Credit_size = 0.12")
        constants_section.append("global $press_effect = 0.002")
        constants_section.append("global $ButtonLayerGeneration = 0")
        constants_section.append("global $UI_Thickness = 0.002")
        constants_section.append("global $x_random = -0.01701")
        constants_section.append("global $res_width = 0")
        constants_section.append("global $res_height = 0")
        constants_section.append("global $ActiveCharacter = 0")
        constants_section.new_line()

        constants_section.append("; 流光边框控制参数")
        constants_section.append("global persist $ui_fx_phase = 0")
        constants_section.append("global $ui_fx_speed = 0.006")
        constants_section.append("global $ui_fx_intensity = " + ("1" if GlobalProperties.generate_branch_mod_gui_flow_effect() else "0"))
        constants_section.new_line()

        constants_section.append(";设置按钮总数")
        constants_section.append("global $Button_amount = " + str(len(key_name_mkey_dict.values())))
        constants_section.append(";设置横向最大按钮数")
        constants_section.append("global $Button_horizontal_max = 10")
        constants_section.new_line()

        constants_section.append("global $Button_number = 0")
        constants_section.append("global $Button_now = 0")
        constants_section.append("global $Button_x = 0")
        constants_section.append("global $Button_y = 0")
        constants_section.append("global $Button_frame_x = 0")
        constants_section.append("global $Button_frame_y = 0")
        
        ini_builder.append_section(constants_section)


        key_section = M_IniSection(M_SectionType.Key)

        key_section.append("[KeyToggleUI]")
        key_section.append("condition = $ActiveCharacter")
        key_section.append("key = CTRL ALT")
        key_section.append("type = hold")
        key_section.append("$menu = 1")
        key_section.new_line()

        key_section.append("[KeyMouse]")
        key_section.append("condition = $menu")
        key_section.append("key = VK_LBUTTON")
        key_section.append("type = hold")
        key_section.append("$mouse_clicked = 1")
        key_section.append("$mouse_hold = 1")
        key_section.new_line()

        ini_builder.append_section(key_section)


        present_section = M_IniSection(M_SectionType.Present)
        present_section.SectionName = "Present"
        present_section.append("post $ActiveCharacter = 0")
        present_section.append("if $menu")
        present_section.append("    run = CommandListPassWindowInfo")
        present_section.new_line()

        present_section.append("    $Button_outer_x = $x_size_Button + $Button_frame_pad * 2")
        present_section.append("    $Button_outer_y = $y_size_Button + $Button_frame_pad * 2")
        present_section.new_line()

        present_section.append("    if $Button_amount > $Button_horizontal_max")
        present_section.append("        $x_size = (($Button_outer_x + $gap) * $Button_horizontal_max) + $gap * 3")
        present_section.append("    else")
        present_section.append("        $x_size = (($Button_outer_x + $gap) * $Button_amount) + $gap * 3")
        present_section.append("    endif")
        present_section.append("    $y_size = (($Button_outer_y + $gap) * ((($Button_amount - 1) // $Button_horizontal_max) + 1) + $gap * 3 + ($Button_outer_y * 0.66) * 2) * res_width / res_height")
        present_section.new_line()

        present_section.append("    if $x_Title_size > $x_size")
        present_section.append("        $x_size = $x_Title_size")
        present_section.append("    endif")
        present_section.append("    if $final_x_off == -1")
        present_section.append("        $final_x_off = 0.5 - $x_size/2 + -0.01701")
        present_section.append("    endif")
        present_section.append("    $ui_fx_phase = $ui_fx_phase + $ui_fx_speed")
        present_section.append("    if $ui_fx_phase >= 4096")
        present_section.append("        $ui_fx_phase = $ui_fx_phase - 4096")
        present_section.append("    endif")
        present_section.new_line()

        present_section.append("    run = CommandListDrawUIElement")
        present_section.append("    run = CommandListDrawUITitle")
        present_section.append("    run = CommandListDrawUICredit")
        present_section.append("    run = CommandListDrawUIBorderXUpper")
        present_section.append("    run = CommandListDrawUIBorderXLower")
        present_section.append("    run = CommandListDrawUIBorderXMiddle")
        present_section.append("    run = CommandListDrawUIBorderXMiddle2")
        present_section.append("    run = CommandListDrawUIBorderYLeft")
        present_section.append("    run = CommandListDrawUIBorderYRight")
        present_section.new_line()

        present_section.append("    ;添加按钮")
        for mkey in key_name_mkey_dict.values():
            present_section.append("    run = CommandListAddButton")
        present_section.new_line()

        present_section.append("    $Button_number = 0")
        present_section.new_line()

        present_section.append("    run = CommandListCheckMouse")
        present_section.append("endif")

        ini_builder.append_section(present_section)

        commandlist_section = M_IniSection(M_SectionType.CommandList)
        commandlist_section.append(";MARK:ButtonSetting")
        commandlist_section.append("[CommandListSetButtonCondition]")
        commandlist_section.append(";设置按钮功能")

        button_number = 0
        for mkey in key_name_mkey_dict.values():
            if button_number == 0:
                commandlist_section.append("if $Button_number == " + str(button_number + 1))
            else:
                commandlist_section.append("else if $Button_number == " + str(button_number + 1))
            key_tmp_name = mkey.key_name
            commandlist_section.append("    if " + key_tmp_name + " < " + str(len(mkey.value_list) - 1))
            commandlist_section.append("        " + key_tmp_name + " = " + key_tmp_name + " + 1" )
            commandlist_section.append("    else")
            commandlist_section.append("        " + key_tmp_name + " = 0")
            commandlist_section.append("    endif")

            button_number = button_number + 1
        commandlist_section.append("endif")
        commandlist_section.new_line()


        commandlist_section.append("[CommandListSetButtonIcon]")
        commandlist_section.append(";设置按钮图标")
        button_number = 0
        for mkey in key_name_mkey_dict.values():
            if button_number == 0:
                commandlist_section.append("if $Button_number == " + str(button_number + 1))
            else:
                commandlist_section.append("else if $Button_number == " + str(button_number + 1))
            commandlist_section.append("    ps-t100 = ResourceButton_item_default_" + str(button_number + 1))
            button_number = button_number + 1

        commandlist_section.append("else")
        commandlist_section.append("    ps-t100 = ResourceButton_item_default")
        commandlist_section.append("endif")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListSetUIShaderParamsDefault]")
        commandlist_section.append("; 默认贴图直出")
        commandlist_section.append("x88 = 0")
        commandlist_section.append("y88 = 0")
        commandlist_section.append("x89 = 0")
        commandlist_section.append("y89 = 0")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListSetUIShaderParamsBorder]")
        commandlist_section.append("; 唯一动态样式：统一炫彩边框")
        commandlist_section.append("x88 = 5")
        commandlist_section.append("y88 = $ui_fx_phase")
        commandlist_section.append("x89 = $ui_fx_intensity")
        commandlist_section.append("y89 = 0")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListPassWindowInfo]")
        commandlist_section.append("if window_width >= 640")
        commandlist_section.append("    $res_width = window_width")
        commandlist_section.append("    $res_height = window_height")
        commandlist_section.append("else if rt_width >= 640")
        commandlist_section.append("    $res_width = rt_width")
        commandlist_section.append("    $res_height = rt_height")
        commandlist_section.append("else if res_width >= 640")
        commandlist_section.append("    $res_width = res_width")
        commandlist_section.append("    $res_height = res_height")
        commandlist_section.append("else")
        commandlist_section.append("    $res_width = $window_width")
        commandlist_section.append("    $res_height = $window_height")
        commandlist_section.append("endif")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListAddButton]")
        commandlist_section.append("$Button_number = $Button_number + 1")
        commandlist_section.append("if $Button_number <= $Button_amount")
        commandlist_section.append("    run = CommandListButtonBlock")
        commandlist_section.append("endif")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListButtonBlock]")
        commandlist_section.append("$Button_frame_x = $final_x_off + (($Button_outer_x + $gap) * (($Button_number - 1) % $Button_horizontal_max ) + $gap * 2)")
        commandlist_section.append("$Button_frame_y = $final_y_off + ((($Button_outer_y + $gap)  * (($Button_number - 1) // $Button_horizontal_max) + $y_offset_button ) * res_width / res_height)")
        commandlist_section.append("$Button_x = $Button_frame_x + $Button_frame_pad")
        commandlist_section.append("$Button_y = $Button_frame_y + ($Button_frame_pad * res_width / res_height)")
        commandlist_section.append("run = CommandListDrawButtonBase")
        commandlist_section.append("run = CommandListDrawButtonFrame")
        commandlist_section.append("; Hover / press glow is drawn before icon so the item art stays readable")
        commandlist_section.append("if cursor_y > $Button_frame_y && cursor_y < $Button_frame_y + ($Button_outer_y * res_width / res_height)")
        commandlist_section.append("    ; BUTTON")
        commandlist_section.append("    if $Button_amount >= $Button_number")
        commandlist_section.append("        if cursor_x > $Button_frame_x && cursor_x < $Button_frame_x + $Button_outer_x")
        commandlist_section.append("            if $mouse_clicked")
        commandlist_section.append("                $Button_now = $Button_number")
        commandlist_section.append("                run = CommandListSetButtonCondition")
        commandlist_section.append("            endif")
        commandlist_section.append("        endif")
        commandlist_section.append("    endif")
        commandlist_section.append("endif")
        commandlist_section.append("run = CommandListDrawButtonIcon")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListCheckMouse]")
        commandlist_section.append("$mouse_clicked = 0")
        commandlist_section.append("if $is_dragging == 1")
        commandlist_section.append("    if $mouse_hold")
        commandlist_section.append("        run = CommandListMoveUIElement")
        commandlist_section.append("    else")
        commandlist_section.append("        $is_dragging = 0")
        commandlist_section.append("    endif")
        commandlist_section.append("else if cursor_x > $final_x_off && cursor_x < $final_x_off + $x_size")
        commandlist_section.append("    if cursor_y > $final_y_off && cursor_y < $final_y_off + $y_size")
        commandlist_section.append("        if $mouse_hold")
        commandlist_section.append("            run = CommandListStartDrag")
        commandlist_section.append("            run = CommandListMoveUIElement")
        commandlist_section.append("        else")
        commandlist_section.append("            $is_dragging = 0")
        commandlist_section.append("        endif")
        commandlist_section.append("    endif")
        commandlist_section.append("endif")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawButtonBase]")
        commandlist_section.append("x87 = $x_size_Button")
        commandlist_section.append("y87 = $y_size_Button * res_width / res_height")
        commandlist_section.append("z87 = $Button_x")
        commandlist_section.append("w87 = $Button_y")
        commandlist_section.append("if $is_dragging && $Button_now == $Button_number")
        commandlist_section.append("    w87 = $Button_y + $press_effect")
        commandlist_section.append("endif")
        commandlist_section.append("ps-t100 = ResourceOutlineButton")
        commandlist_section.append("run = CommandListSetUIShaderParamsDefault")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawButtonFrame]")
        commandlist_section.append("x87 = $Button_outer_x")
        commandlist_section.append("y87 = $Button_outer_y * res_width / res_height")
        commandlist_section.append("z87 = $Button_frame_x")
        commandlist_section.append("w87 = $Button_frame_y")
        commandlist_section.append("if $is_dragging && $Button_now == $Button_number")
        commandlist_section.append("    w87 = $Button_frame_y + $press_effect")
        commandlist_section.append("endif")
        commandlist_section.append("ps-t100 = ResourceOutlineButton")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawButtonIcon]")
        commandlist_section.append("x87 = $x_size_Button")
        commandlist_section.append("y87 = $y_size_Button * res_width / res_height")
        commandlist_section.append("z87 = $Button_x")
        commandlist_section.append("w87 = $Button_y")
        commandlist_section.append("if $is_dragging && $Button_now == $Button_number")
        commandlist_section.append("    w87 = $Button_y + $press_effect")
        commandlist_section.append("endif")
        commandlist_section.append("run = CommandListSetButtonIcon")
        commandlist_section.append("run = CommandListSetUIShaderParamsDefault")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIElement]")
        commandlist_section.append("x87 = $x_size")
        commandlist_section.append("y87 = $y_size")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off")
        commandlist_section.append("ps-t100 = ResourceUIBackground")
        commandlist_section.append("run = CommandListSetUIShaderParamsDefault")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUITitle]")
        commandlist_section.append("x87 = $x_Title_size")
        commandlist_section.append("y87 = $y_Title_size")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off")
        commandlist_section.append("ps-t100 = ResourceUITitle")
        commandlist_section.append("run = CommandListSetUIShaderParamsDefault")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUICredit]")
        commandlist_section.append("x87 = $x_Credit_size")
        commandlist_section.append("y87 = $y_Credit_size")
        commandlist_section.append("z87 = $final_x_off + $x_size - $x_Credit_size")
        commandlist_section.append("w87 = $final_y_off + ($y_size - $y_Credit_size)")
        commandlist_section.append("ps-t100 = ResourceUICredit")
        commandlist_section.append("run = CommandListSetUIShaderParamsDefault")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderXUpper]")
        commandlist_section.append("x87 = $x_size")
        commandlist_section.append("y87 = $UI_Thickness * res_width / res_height")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderXLower]")
        commandlist_section.append("x87 = $x_size")
        commandlist_section.append("y87 = $UI_Thickness * res_width / res_height")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off + $y_size - $UI_Thickness")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderXMiddle]")
        commandlist_section.append("x87 = $x_size")
        commandlist_section.append("y87 = $UI_Thickness * res_width / res_height")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off + $y_Title_size - $UI_Thickness")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderXMiddle2]")
        commandlist_section.append("x87 = $x_size")
        commandlist_section.append("y87 = $UI_Thickness * res_width / res_height")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off + $y_size - $y_Credit_size - $UI_Thickness")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderYLeft]")
        commandlist_section.append("x87 = $UI_Thickness")
        commandlist_section.append("y87 = $y_size")
        commandlist_section.append("z87 = $final_x_off")
        commandlist_section.append("w87 = $final_y_off")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListDrawUIBorderYRight]")
        commandlist_section.append("x87 = $UI_Thickness")
        commandlist_section.append("y87 = $y_size")
        commandlist_section.append("z87 = $final_x_off + $x_size - $UI_Thickness")
        commandlist_section.append("w87 = $final_y_off")
        commandlist_section.append("ps-t100 = ResourceUIColorBorder")
        commandlist_section.append("run = CommandListSetUIShaderParamsBorder")
        commandlist_section.append("run = CustomShaderElement")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListStartDrag]")
        commandlist_section.append("if $is_dragging == 0")
        commandlist_section.append("    $drag_start_x = cursor_x - $final_x_off")
        commandlist_section.append("    $drag_start_y = cursor_y - $final_y_off")
        commandlist_section.append("    $is_dragging = 1")
        commandlist_section.append("endif")
        commandlist_section.new_line()

        commandlist_section.append("[CommandListMoveUIElement]")
        commandlist_section.append("if $is_dragging == 1")
        commandlist_section.append("    if $mouse_hold")
        commandlist_section.append("        $new_x_off = cursor_x - $drag_start_x")
        commandlist_section.append("        $new_y_off = cursor_y - $drag_start_y")
        commandlist_section.append("        if $new_x_off < 0")
        commandlist_section.append("            $final_x_off = 0")
        commandlist_section.append("        else if $new_x_off + $x_size > 1")
        commandlist_section.append("            $final_x_off = 1 - $x_size")
        commandlist_section.append("        else")
        commandlist_section.append("            $final_x_off = $new_x_off")
        commandlist_section.append("        endif")
        commandlist_section.append("        if $new_y_off < 0")
        commandlist_section.append("            $final_y_off = 0")
        commandlist_section.append("        else if $new_y_off + $y_size > 1")
        commandlist_section.append("            $final_y_off = 1 - $y_size")
        commandlist_section.append("        else")
        commandlist_section.append("            $final_y_off = $new_y_off")
        commandlist_section.append("        endif")
        commandlist_section.append("    else")
        commandlist_section.append("        $is_dragging = 0")
        commandlist_section.append("    endif")
        commandlist_section.append("endif")
        commandlist_section.new_line()


        commandlist_section.append("[CustomShaderElement]")
        commandlist_section.append("hs = null")
        commandlist_section.append("ds = null")
        commandlist_section.append("gs = null")
        commandlist_section.append("cs = null")
        commandlist_section.append("run = BuiltInCommandListUnbindAllRenderTargets")
        commandlist_section.append("vs = .\\res\\draw_2d.hlsl")
        commandlist_section.append("ps = .\\res\\draw_2d.hlsl")
        commandlist_section.append("blend = ADD SRC_ALPHA INV_SRC_ALPHA")
        commandlist_section.append("cull = none")
        commandlist_section.append("topology = triangle_strip")
        commandlist_section.append("o0 = set_viewport bb")
        commandlist_section.append("Draw = 4,0")
        commandlist_section.new_line()

        ini_builder.append_section(commandlist_section)

        resource_section = M_IniSection(M_SectionType.ResourceTexture)

        resource_section.append("[ResourceUIColorBorder]")
        resource_section.append("filename = .\\res\\Border.png")
        resource_section.new_line()
        
        resource_section.append("[ResourceUIBackground]")
        resource_section.append("filename = .\\res\\Background.png")
        resource_section.new_line()

        resource_section.append("[ResourceUIButtonSelect]")
        resource_section.append("filename = .\\res\\Selected.png")
        resource_section.new_line()
        
        resource_section.append("[ResourceOutlineButton]")
        resource_section.append("filename = .\\res\\Button.png")
        resource_section.new_line()

        resource_section.append("[ResourceButtonPush]")
        resource_section.append("filename = .\\res\\Push.png")
        resource_section.new_line()

        resource_section.append("[ResourceUITitle]")
        resource_section.append("filename = .\\res\\Title.png")
        resource_section.new_line()

        resource_section.append("[ResourceUICredit]")
        resource_section.append("filename = .\\res\\Credits.png")
        resource_section.new_line()

        resource_section.append("[ResourceButton_item_default]")
        resource_section.append("filename = .\\res\\item_shirt.png")
        resource_section.new_line()

        # 测试的自定义资源
        button_number = 0
        for mkey in key_name_mkey_dict.values():
            resource_section.append("[ResourceButton_item_default_"+ str(button_number + 1)+ "]")
            resource_section.append("filename = .\\res\\item_shirt.png")
            resource_section.new_line()
            button_number = button_number + 1

        ini_builder.append_section(resource_section)

        # for mkey in key_name_mkey_dict.values():
        #     key_str = "global persist " + mkey.key_name + " = " + str(mkey.initialize_value)
        #     constants_section.append(key_str) 
