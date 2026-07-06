# MIDI → 红石音乐简谱转换器
# Copyright (C) 2026 wufeng
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import mido
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import sys
from io import StringIO

# 尝试导入拖拽库
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False
    print("⚠️ tkinterdnd2 未安装，拖拽功能不可用")

# ==================== 重定向输出到 GUI ====================

class PrintRedirector:
    """将 print 输出重定向到 GUI 日志"""
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.buffer = StringIO()
    
    def write(self, text):
        if text.strip():
            self.log_callback(text.strip())
            self.buffer.write(text)
    
    def flush(self):
        self.buffer.flush()
    
    def getvalue(self):
        return self.buffer.getvalue()

# ==================== MIDI 转换核心 ====================

WHITE_KEYS = [0, 2, 4, 5, 7, 9, 11]
WHITE_KEY_MAP = {0: '1', 2: '2', 4: '3', 5: '4', 7: '5', 9: '6', 11: '7'}
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def midi_note_to_format(note_number, auto_map_sharp=True):
    if 48 <= note_number <= 59:
        octave = 'l'
        base = 48
    elif 60 <= note_number <= 71:
        octave = 'm'
        base = 60
    elif 72 <= note_number <= 83:
        octave = 'h'
        base = 72
    else:
        return None, None
    
    semitone = (note_number - base) % 12
    note_name = NOTE_NAMES[semitone]
    
    if '#' in note_name:
        if auto_map_sharp:
            nearest = min(WHITE_KEYS, key=lambda x: abs(x - semitone))
            note_num = WHITE_KEY_MAP[nearest]
            return f"{octave}{note_num}", f"({note_name}→{note_num})"
        else:
            return None, None
    else:
        return f"{octave}{WHITE_KEY_MAP[semitone]}", None


def midi_to_sequence(midi_path, min_velocity=1, take_highest=True, auto_map_sharp=True):
    try:
        mid = mido.MidiFile(midi_path)
        notes_by_time = {}
        tempo = 500000
        ticks_per_beat = mid.ticks_per_beat
        total_notes = 0
        mapped_sharps = 0
        
        for track in mid.tracks:
            track_time = 0
            for msg in track:
                track_time += msg.time
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
                if msg.type == 'note_on' and msg.velocity > min_velocity:
                    total_notes += 1
                    seconds = mido.tick2second(track_time, ticks_per_beat, tempo)
                    time_key = round(seconds, 1)
                    if time_key not in notes_by_time:
                        notes_by_time[time_key] = []
                    notes_by_time[time_key].append(msg.note)
        
        result = []
        mapping_info = []
        last_time = 0
        skipped_count = 0
        
        for time_key in sorted(notes_by_time.keys()):
            notes = notes_by_time[time_key]
            notes_to_process = [max(notes)] if take_highest else notes
            
            for note in notes_to_process:
                note_str, map_info = midi_note_to_format(note, auto_map_sharp)
                if note_str is None:
                    skipped_count += 1
                    continue
                if map_info:
                    mapped_sharps += 1
                
                time_gap = time_key - last_time
                if time_gap > 0:
                    t_count = max(1, int(time_gap))
                    result.extend(['t1'] * t_count)
                
                result.append(note_str)
                mapping_info.append(f"{note_str}{map_info}" if map_info else note_str)
                last_time = time_key
        
        status = f"""
📊 转换统计:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 原始音符总数: {total_notes}
⏱️  时间切片数: {len(notes_by_time)}
🎵 有效音符数: {len(result) - result.count('t1')}
📏 总序列长度: {len(result)} 个元素
🔄 升降音映射: {mapped_sharps} 个
⏭️  跳过音符: {skipped_count} 个
"""
        return result, mapping_info, status
    
    except Exception as e:
        return None, None, f"❌ 错误: {str(e)}"


# ==================== GUI 界面 ====================

class MidiToNoteGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MIDI → 红石音乐简谱转换器")
        self.root.geometry("800x750")
        self.root.resizable(True, True)
        
        self.current_file = None
        self.result_sequence = None
        self.mapping_info = None
        
        # 保存原始 stdout
        self.original_stdout = sys.stdout
        
        self.setup_ui()
        self.setup_drag_drop()
        
        # 设置输出重定向
        self.redirector = PrintRedirector(self.log)
        sys.stdout = self.redirector
    
    def setup_ui(self):
        """构建界面"""
        title = tk.Label(self.root, text="🎵 MIDI → 红石音乐简谱转换器", 
                         font=("微软雅黑", 16, "bold"))
        title.pack(pady=10)
        
        info = tk.Label(self.root, text="拖拽 .mid 或 .midi 文件到下方区域，或点击按钮选择文件",
                        font=("微软雅黑", 10), fg="gray")
        info.pack(pady=5)
        
        # ===== 文件选择区域 =====
        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10, padx=20, fill=tk.X)
        
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(frame_top, textvariable=self.path_var, 
                                   font=("Consolas", 10), state='readonly')
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        btn_browse = tk.Button(frame_top, text="📂 浏览", command=self.browse_file,
                               font=("微软雅黑", 10), width=10)
        btn_browse.pack(side=tk.RIGHT)
        
        # ===== 选项区域 =====
        options_frame = tk.LabelFrame(self.root, text="⚙️ 转换选项", font=("微软雅黑", 10))
        options_frame.pack(pady=10, padx=20, fill=tk.X)
        
        self.take_highest_var = tk.BooleanVar(value=True)
        cb_highest = tk.Checkbutton(options_frame, text="只取最高音（主旋律）", 
                                    variable=self.take_highest_var,
                                    font=("微软雅黑", 10))
        cb_highest.pack(side=tk.LEFT, padx=10)
        
        self.auto_map_var = tk.BooleanVar(value=True)
        cb_map = tk.Checkbutton(options_frame, text="升降音自动映射到最近自然音", 
                                variable=self.auto_map_var,
                                font=("微软雅黑", 10))
        cb_map.pack(side=tk.LEFT, padx=20)
        
        # ===== 拖拽提示区域 =====
        self.drop_frame = tk.LabelFrame(self.root, text="📥 拖拽文件到这里", 
                                        font=("微软雅黑", 11), height=80)
        self.drop_frame.pack(pady=10, padx=20, fill=tk.X)
        
        drop_label = tk.Label(self.drop_frame, text="将 .mid 或 .midi 文件拖入此区域",
                              font=("微软雅黑", 11), fg="#666")
        drop_label.pack(pady=20)
        
        # ===== 按钮区域 =====
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        self.btn_convert = tk.Button(btn_frame, text="🔄 转换", command=self.convert_file,
                                     font=("微软雅黑", 11), bg="#4CAF50", fg="white",
                                     width=12, height=1, state=tk.DISABLED)
        self.btn_convert.pack(side=tk.LEFT, padx=5)
        
        self.btn_save = tk.Button(btn_frame, text="💾 保存", command=self.save_result,
                                  font=("微软雅黑", 11), bg="#2196F3", fg="white",
                                  width=12, height=1, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=5)
        
        self.btn_run = tk.Button(btn_frame, text="🚀 运行", command=self.run_sequence,
                                 font=("微软雅黑", 11), bg="#FF9800", fg="white",
                                 width=12, height=1, state=tk.DISABLED)
        self.btn_run.pack(side=tk.LEFT, padx=5)
        
        self.btn_clear = tk.Button(btn_frame, text="🗑️ 清空", command=self.clear_all,
                                   font=("微软雅黑", 11), width=10, height=1)
        self.btn_clear.pack(side=tk.LEFT, padx=5)
        
        # ===== 日志输出区域（新增） =====
        log_frame = tk.LabelFrame(self.root, text="📋 系统日志（包含 print 输出）", 
                                  font=("微软雅黑", 10))
        log_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # 添加清空日志按钮
        log_btn_frame = tk.Frame(log_frame)
        log_btn_frame.pack(fill=tk.X, padx=5, pady=2)
        
        btn_clear_log = tk.Button(log_btn_frame, text="🗑️ 清空日志", 
                                  command=self.clear_log, font=("微软雅黑", 9),
                                  width=10)
        btn_clear_log.pack(side=tk.RIGHT)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9),
                                                   height=8, wrap=tk.WORD)
        self.log_text.pack(pady=5, padx=5, fill=tk.X)
        self.log_text.config(state=tk.DISABLED)
        
        # ===== 转换状态区域 =====
        status_frame = tk.LabelFrame(self.root, text="📊 转换状态", 
                                     font=("微软雅黑", 10))
        status_frame.pack(pady=10, padx=20, fill=tk.X)
        
        self.status_text = scrolledtext.ScrolledText(status_frame, font=("Consolas", 10),
                                                      height=6, wrap=tk.WORD)
        self.status_text.pack(pady=5, padx=5, fill=tk.X)
        self.status_text.config(state=tk.DISABLED)
        
        # ===== 结果预览区域 =====
        preview_label = tk.Label(self.root, text="📋 转换结果预览 (前200个元素)",
                                 font=("微软雅黑", 10, "bold"))
        preview_label.pack(anchor=tk.W, padx=20)
        
        self.preview_text = scrolledtext.ScrolledText(self.root, font=("Consolas", 10),
                                                       height=10, wrap=tk.WORD)
        self.preview_text.pack(pady=5, padx=20, fill=tk.BOTH, expand=True)
        self.preview_text.config(state=tk.DISABLED)
        
        # 状态栏
        self.status_bar = tk.Label(self.root, text="就绪", anchor=tk.W,
                                   font=("微软雅黑", 9), fg="gray")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=5)
    
    def setup_drag_drop(self):
        if HAS_DND:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.on_drop)
                self.path_entry.drop_target_register(DND_FILES)
                self.path_entry.dnd_bind('<<Drop>>', self.on_drop)
                self.drop_frame.drop_target_register(DND_FILES)
                self.drop_frame.dnd_bind('<<Drop>>', self.on_drop)
                self.log("✅ 拖拽功能已启用")
            except Exception as e:
                self.log(f"⚠️ 拖拽功能不可用: {e}")
        else:
            self.log("ℹ️ 使用浏览按钮选择文件")
    
    def log(self, message):
        """向日志区域添加消息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        # 同时更新状态栏
        if len(message) < 60:
            self.update_status(message[:60])
    
    def clear_log(self):
        """清空日志区域"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log("🗑️ 日志已清空")
    
    def set_status(self, message):
        """设置转换状态"""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(1.0, message)
        self.status_text.config(state=tk.DISABLED)
        self.status_text.see(tk.END)
    
    def append_status(self, message):
        """追加转换状态"""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)
    
    def set_preview(self, text):
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(1.0, text)
        self.preview_text.config(state=tk.DISABLED)
    
    def update_status(self, message):
        self.status_bar.config(text=message)
        self.root.update_idletasks()
    
    def on_drop(self, event):
        if not HAS_DND:
            return
        try:
            files = event.data
            if files:
                if isinstance(files, str):
                    files = files.strip('{}').split()
                if files:
                    file_path = files[0].strip('"').strip("'")
                    self.load_file(file_path)
        except Exception as e:
            self.log(f"⚠️ 拖拽处理出错: {e}")
    
    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 MIDI 文件",
            filetypes=[("MIDI 文件", "*.mid *.midi"), ("所有文件", "*.*")]
        )
        if file_path:
            self.load_file(file_path)
    
    def load_file(self, file_path):
        file_path = file_path.strip('"').strip("'")
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ['.mid', '.midi']:
            messagebox.showwarning("警告", "请选择 .mid 或 .midi 文件！")
            return
        if not os.path.exists(file_path):
            messagebox.showerror("错误", "文件不存在！")
            return
        
        self.current_file = file_path
        self.path_var.set(file_path)
        self.btn_convert.config(state=tk.NORMAL)
        self.log(f"📂 已加载: {os.path.basename(file_path)}")
        self.update_status(f"已加载: {os.path.basename(file_path)}")
        self.convert_file()
    
    def convert_file(self):
        if not self.current_file:
            return
        
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.update_status("正在转换...")
        self.log("🔄 开始转换...")
        
        take_highest = self.take_highest_var.get()
        auto_map = self.auto_map_var.get()
        
        def do_convert():
            sequence, mapping_info, status = midi_to_sequence(
                self.current_file, 
                take_highest=take_highest,
                auto_map_sharp=auto_map
            )
            self.root.after(0, lambda: self.on_convert_done(sequence, mapping_info, status))
        
        threading.Thread(target=do_convert, daemon=True).start()
    
    def on_convert_done(self, sequence, mapping_info, status):
        self.set_status(status)
        
        if sequence is not None and len(sequence) > 0:
            self.result_sequence = sequence
            self.mapping_info = mapping_info
            
            preview = str(sequence[:200])
            if len(sequence) > 200:
                preview += f"\n\n... 共 {len(sequence)} 个元素"
            
            self.set_preview(preview)
            self.btn_save.config(state=tk.NORMAL)
            self.btn_run.config(state=tk.NORMAL)
            self.update_status(f"✅ 转换完成！共 {len(sequence)} 个元素")
            self.log(f"✅ 转换完成，共 {len(sequence)} 个音符元素")
        else:
            self.set_preview("❌ 转换失败，未生成有效音符")
            self.btn_save.config(state=tk.DISABLED)
            self.btn_run.config(state=tk.DISABLED)
            self.update_status("❌ 转换失败")
            self.log("❌ 转换失败")
        
        self.btn_convert.config(state=tk.NORMAL)
    
    def run_sequence(self):
        """运行序列 - 点击 '运行' 按钮执行"""
        if not self.result_sequence:
            messagebox.showwarning("警告", "请先转换 MIDI 文件！")
            return
        
        note_list = self.result_sequence
        self.log(f"🚀 开始运行程序，共 {len(note_list)} 个元素")
        self.update_status("运行中...")
        self.btn_run.config(state=tk.DISABLED)
        
        def do_run():
            try:
                # 运行时会自动将 print 输出重定向到日志
                run_start(note_list)
                
                self.root.after(0, lambda: self.log("✅ 程序执行完成！"))
                self.root.after(0, lambda: self.update_status("执行完成"))
                
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ 运行出错: {e}"))
                self.root.after(0, lambda: self.update_status("运行出错"))
            finally:
                self.root.after(0, lambda: self.btn_run.config(state=tk.NORMAL))
        
        threading.Thread(target=do_run, daemon=True).start()
    
    def save_result(self):
        if not self.result_sequence:
            messagebox.showwarning("警告", "没有可保存的结果！")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="保存转换结果",
            defaultextension=".py",
            filetypes=[("Python 文件", "*.py"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# 由 MIDI 自动生成的红石音乐简谱序列\n")
                f.write(f"# 来源: {os.path.basename(self.current_file)}\n")
                f.write(f"# 元素总数: {len(self.result_sequence)}\n")
                f.write("note_sequence = [\n")
                
                line = []
                for i, item in enumerate(self.result_sequence):
                    line.append(f"'{item}'")
                    if len(line) >= 20:
                        f.write("    " + ", ".join(line) + ",\n")
                        line = []
                
                if line:
                    f.write("    " + ", ".join(line) + "\n")
                f.write("]\n")
            
            self.log(f"💾 已保存到: {file_path}")
            self.update_status(f"✅ 已保存到: {os.path.basename(file_path)}")
            messagebox.showinfo("成功", f"文件已保存到:\n{file_path}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def clear_all(self):
        self.current_file = None
        self.result_sequence = None
        self.mapping_info = None
        self.path_var.set("")
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.set_preview("")
        self.set_status("")
        self.log("🗑️ 已清空所有数据")
        self.update_status("就绪")
    
    def on_closing(self):
        """关闭窗口时恢复 stdout"""
        sys.stdout = self.original_stdout
        self.root.destroy()


# ==================== 红石音乐执行函数 ====================

def run_start(commond_list):
    import time
    import pydirectinput
    import pyperclip
    from pynput.keyboard import Key, Controller
    import ctypes
    import sys

    def start():
        print('准备时间(5s),请快速调至游戏窗口')
        time.sleep(5)

        keyboard = Controller()
        caps_state = ctypes.windll.user32.GetKeyState(0x14) & 1
        if caps_state == 0:
            keyboard.press(Key.caps_lock)
            keyboard.release(Key.caps_lock)
            print("✅ Caps Lock 已开启")
        else:
            print("ℹ️ Caps Lock 已经是开启状态")

        time.sleep(2)

        print("start程序已开始")
        pydirectinput.press('t')
        pyperclip.copy('/tp @s ~ ~ ~ 0 90')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        time.sleep(0.5)
        pydirectinput.press('space')
        time.sleep(0.1)
        pydirectinput.press('space')
        pydirectinput.press('space')
        pydirectinput.press('t')
        pyperclip.copy('/clear @s')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('t')
        pyperclip.copy('/give @s minecraft:repeater')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('t')
        pyperclip.copy('/give @s minecraft:note_block')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')

    def t1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('1')
        pydirectinput.click(button='right')

    def l1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')

    def l2():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def l3():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def l4():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def l5():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def l6():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def l7():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')

    def m2():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m3():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m4():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m5():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m6():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def m7():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')

    def h2():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h3():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h4():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h5():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h6():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    def h7():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        time.sleep(0.5)
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')
        pydirectinput.click(button='right')

    # 字符串 → 函数映射
    action_map = {
        't1': t1,
        'l1': l1,
        'l2': l2,
        'l3': l3,
        'l4': l4,
        'l5': l5,
        'l6': l6,
        'l7': l7,
        'm1': m1,
        'm2': m2,
        'm3': m3,
        'm4': m4,
        'm5': m5,
        'm6': m6,
        'm7': m7,
        'h1': h1,
        'h2': h2,
        'h3': h3,
        'h4': h4,
        'h5': h5,
        'h6': h6,
        'h7': h7,
    }

    print("检测到程序开始")
    start()

    for item in commond_list:
        func = action_map.get(item)
        if func:
            func()
        else:
            print(f"⚠️ 未知指令: {item}")


# ==================== 启动程序 ====================

if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    
    app = MidiToNoteGUI(root)
    
    # 设置窗口关闭事件
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    root.mainloop()