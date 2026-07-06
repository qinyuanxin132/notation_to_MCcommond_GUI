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
import winsound
import time

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

# ==================== MIDI 工具函数 ====================

def get_midi_tracks(midi_path):
    """获取 MIDI 文件的轨道列表及其音符数量"""
    try:
        mid = mido.MidiFile(midi_path)
        tracks_info = []
        
        for i, track in enumerate(mid.tracks):
            note_count = 0
            track_name = f"轨道 {i+1}"
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    note_count += 1
                if msg.type == 'track_name':
                    track_name = msg.name.strip() or f"轨道 {i+1}"
            if note_count > 0:
                tracks_info.append((i, track_name, note_count))
        
        return tracks_info
    except Exception as e:
        return []

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


def midi_to_sequence(midi_path, min_velocity=1, take_highest=True, auto_map_sharp=True, spacing=1.0, max_jump=3, selected_track=None):
    """
    事件驱动模式：读取每个音符的按下(note_on)
    同一时间点只保留一个音符（最高音），其他丢弃
    selected_track: 选中的轨道索引 (None=全部, 0=第一个轨道)
    """
    try:
        mid = mido.MidiFile(midi_path)
        ticks_per_beat = mid.ticks_per_beat
        tempo = 500000
        
        # 获取 tempo
        for track in mid.tracks:
            for msg in track:
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
                    break
            if tempo != 500000:
                break
        
        # ===== 收集所有 note_on 事件，按时间分组 =====
        notes_by_time = {}
        
        for track_idx, track in enumerate(mid.tracks):
            # 如果指定了轨道，只处理该轨道
            if selected_track is not None and track_idx != selected_track:
                continue
            
            abs_time = 0
            for msg in track:
                abs_time += msg.time
                seconds = mido.tick2second(abs_time, ticks_per_beat, tempo)
                seconds = round(seconds, 1)  # 四舍五入到 0.1 秒
                
                if msg.type == 'note_on' and msg.velocity > min_velocity:
                    note_str, _ = midi_note_to_format(msg.note, auto_map_sharp)
                    if note_str:
                        if seconds not in notes_by_time:
                            notes_by_time[seconds] = []
                        notes_by_time[seconds].append((msg.note, note_str))
        
        if not notes_by_time:
            track_info = f"轨道 {selected_track+1}" if selected_track is not None else "全部轨道"
            return None, None, f"❌ 在 {track_info} 中未检测到有效音符"
        
        result = []
        mapping_info = []
        last_time = 0
        skipped_count = 0
        last_note_str = None
        
        for time_key in sorted(notes_by_time.keys()):
            notes = notes_by_time[time_key]
            
            # ===== 同一时间只保留一个音符 =====
            if take_highest:
                # 取最高音（音高数值最大的）
                notes.sort(key=lambda x: x[0], reverse=True)
            # 只取第一个（最高音或第一个）
            note_number, note_str = notes[0]
            
            # 计算时间间隔
            time_gap = time_key - last_time
            if time_gap > 0:
                t_count = max(1, int(round(time_gap * spacing * 5)))
                if max_jump > 0:
                    t_count = min(t_count, max_jump)
                result.extend(['t1'] * t_count)
            
            # 抑制重复音符（连续相同的音只保留第一个）
            if note_str == last_note_str:
                skipped_count += 1
                continue
            last_note_str = note_str
            
            result.append(note_str)
            mapping_info.append(note_str)
            last_time = time_key
        
        # 统计跳过了多少音符（同一时间点的其他音符）
        total_notes = sum(len(v) for v in notes_by_time.values())
        dropped_notes = total_notes - len(notes_by_time)
        
        track_info = f"轨道 {selected_track+1}" if selected_track is not None else "全部轨道"
        
        status = f"""
📊 转换统计:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 原始音符总数: {total_notes}
🎵 保留音符数: {len(notes_by_time)}
📏 总序列长度: {len(result)} 个元素
📐 间距倍数: {spacing}x
🦘 最大跳跃: {max_jump} 格
⏭️  丢弃同时间音符: {dropped_notes} 个
⏭️  跳过重复音符: {skipped_count} 个
🎵 使用轨道: {track_info}
"""
        return result, mapping_info, status
    
    except Exception as e:
        return None, None, f"❌ 错误: {str(e)}"


# ==================== 试听功能 ====================

# 音符频率映射 (低音 l, 中音 m, 高音 h)
NOTE_FREQ = {
    'l1': 262, 'l2': 294, 'l3': 330, 'l4': 349, 'l5': 392, 'l6': 440, 'l7': 494,
    'm1': 523, 'm2': 587, 'm3': 659, 'm4': 698, 'm5': 784, 'm6': 880, 'm7': 988,
    'h1': 1047, 'h2': 1175, 'h3': 1319, 'h4': 1397, 'h5': 1568, 'h6': 1760, 'h7': 1967,
}


def play_preview(sequence, duration=80, stop_event=None):
    """
    播放预览序列
    sequence: 音符序列
    duration: 每个音符的持续时间(毫秒)
    stop_event: 停止事件，用于提前终止播放
    """
    for item in sequence:
        if stop_event and stop_event.is_set():
            print("⏹️ 试听已停止")
            break
        
        if item == 't1':
            time.sleep(duration / 1000.0)
        elif item in NOTE_FREQ:
            freq = NOTE_FREQ[item]
            winsound.Beep(freq, duration)
            time.sleep(duration / 2000.0)
        else:
            continue


# ==================== 全局停止快捷键 ====================
STOP_KEY = 'b'


def get_stop_key():
    return STOP_KEY


def set_stop_key(key):
    global STOP_KEY
    STOP_KEY = key.lower()


# ==================== GUI 界面 ====================

class MidiToNoteGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MIDI → 红石音乐简谱转换器")
        self.root.geometry("850x920")
        self.root.resizable(True, True)
        
        self.current_file = None
        self.result_sequence = None
        self.mapping_info = None
        self.preview_stop_event = None
        
        self.original_stdout = sys.stdout
        
        self.setup_ui()
        self.setup_drag_drop()
        
        self.redirector = PrintRedirector(self.log)
        sys.stdout = self.redirector
    
    def setup_ui(self):
        title = tk.Label(self.root, text="🎵 MIDI → 红石音乐简谱转换器", 
                         font=("微软雅黑", 16, "bold"))
        title.pack(pady=10)
        
        info = tk.Label(self.root, text="拖拽 .mid 或 .midi 文件到下方区域，或点击按钮选择文件",
                        font=("微软雅黑", 10), fg="gray")
        info.pack(pady=5)
        
        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10, padx=20, fill=tk.X)
        
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(frame_top, textvariable=self.path_var, 
                                   font=("Consolas", 10), state='readonly')
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        btn_browse = tk.Button(frame_top, text="📂 浏览", command=self.browse_file,
                               font=("微软雅黑", 10), width=10)
        btn_browse.pack(side=tk.RIGHT)
        
        options_frame = tk.LabelFrame(self.root, text="⚙️ 转换选项", font=("微软雅黑", 10))
        options_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # 第一行：复选框
        row1 = tk.Frame(options_frame)
        row1.pack(fill=tk.X, pady=2)
        
        self.take_highest_var = tk.BooleanVar(value=True)
        cb_highest = tk.Checkbutton(row1, text="只取最高音（主旋律）", 
                                    variable=self.take_highest_var,
                                    font=("微软雅黑", 10))
        cb_highest.pack(side=tk.LEFT, padx=10)
        
        self.auto_map_var = tk.BooleanVar(value=True)
        cb_map = tk.Checkbutton(row1, text="升降音自动映射到最近自然音", 
                                variable=self.auto_map_var,
                                font=("微软雅黑", 10))
        cb_map.pack(side=tk.LEFT, padx=20)
        
        # 第二行：间距倍数
        row2 = tk.Frame(options_frame)
        row2.pack(fill=tk.X, pady=2)
        
        tk.Label(row2, text="📏 间距倍数:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        
        self.spacing_var = tk.DoubleVar(value=1.0)
        spacing_spinbox = tk.Spinbox(
            row2,
            from_=0.1,
            to=5.0,
            increment=0.1,
            textvariable=self.spacing_var,
            font=("微软雅黑", 10),
            width=6
        )
        spacing_spinbox.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row2, text="(0.1-5.0倍)", font=("微软雅黑", 9), fg="gray").pack(side=tk.LEFT, padx=5)
        
        preset_frame = tk.Frame(row2)
        preset_frame.pack(side=tk.LEFT, padx=10)
        
        def set_spacing(val):
            self.spacing_var.set(val)
        
        for val in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
            btn = tk.Button(preset_frame, text=str(val), command=lambda v=val: set_spacing(v),
                           font=("微软雅黑", 8), width=4, relief=tk.RIDGE)
            btn.pack(side=tk.LEFT, padx=1)
        
        tk.Label(row2, text="(数值越大t1越多，节奏越慢)", font=("微软雅黑", 9), fg="green").pack(side=tk.LEFT, padx=10)
        
        # 第三行：最大跳跃
        row3 = tk.Frame(options_frame)
        row3.pack(fill=tk.X, pady=2)
        
        tk.Label(row3, text="🦘 最大跳跃:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        
        self.max_jump_var = tk.IntVar(value=3)
        max_jump_spinbox = tk.Spinbox(
            row3,
            from_=0,
            to=5,
            increment=1,
            textvariable=self.max_jump_var,
            font=("微软雅黑", 10),
            width=4
        )
        max_jump_spinbox.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row3, text="(0=不限, 1-5=限制格数)", font=("微软雅黑", 9), fg="gray").pack(side=tk.LEFT, padx=5)
        
        # ===== 第四行：轨道选择 =====
        row4 = tk.Frame(options_frame)
        row4.pack(fill=tk.X, pady=2)
        
        tk.Label(row4, text="🎵 选择轨道:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=10)
        
        self.track_var = tk.StringVar(value="全部")
        self.track_combobox = ttk.Combobox(
            row4,
            textvariable=self.track_var,
            font=("微软雅黑", 10),
            width=35,
            state="readonly"
        )
        self.track_combobox.pack(side=tk.LEFT, padx=5)
        self.track_combobox['values'] = ["全部"]
        
        tk.Label(row4, text="(选择要转换的轨道)", font=("微软雅黑", 9), fg="gray").pack(side=tk.LEFT, padx=5)
        
        hotkey_frame = tk.LabelFrame(self.root, text="⌨️ 快捷键设置", font=("微软雅黑", 10))
        hotkey_frame.pack(pady=5, padx=20, fill=tk.X)
        
        hotkey_row = tk.Frame(hotkey_frame)
        hotkey_row.pack(fill=tk.X, pady=5, padx=10)
        
        tk.Label(hotkey_row, text="停止运行快捷键:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        
        self.hotkey_var = tk.StringVar(value='B')
        hotkey_entry = tk.Entry(
            hotkey_row,
            textvariable=self.hotkey_var,
            font=("Consolas", 11, "bold"),
            width=6,
            justify='center',
            relief=tk.RIDGE
        )
        hotkey_entry.pack(side=tk.LEFT, padx=10)
        
        def apply_hotkey():
            key = self.hotkey_var.get().strip().lower()
            if len(key) == 1 and key.isalpha():
                set_stop_key(key)
                self.log(f"⌨️ 停止快捷键已设置为: {key.upper()}")
                messagebox.showinfo("成功", f"停止快捷键已设置为: {key.upper()}")
            else:
                messagebox.showwarning("警告", "请输入单个字母 (a-z)")
                self.hotkey_var.set(get_stop_key().upper())
        
        btn_apply_hotkey = tk.Button(
            hotkey_row,
            text="✅ 应用",
            command=apply_hotkey,
            font=("微软雅黑", 9),
            bg="#4CAF50",
            fg="white",
            width=6
        )
        btn_apply_hotkey.pack(side=tk.LEFT, padx=5)
        
        tk.Label(
            hotkey_row,
            text=f"(当前: {get_stop_key().upper()})",
            font=("微软雅黑", 9),
            fg="gray"
        ).pack(side=tk.LEFT, padx=10)
        
        tk.Label(
            hotkey_row,
            text="💡 运行时按下此键可立即停止",
            font=("微软雅黑", 9),
            fg="orange"
        ).pack(side=tk.LEFT, padx=10)
        
        self.drop_frame = tk.LabelFrame(self.root, text="📥 拖拽文件到这里", 
                                        font=("微软雅黑", 11), height=80)
        self.drop_frame.pack(pady=10, padx=20, fill=tk.X)
        
        drop_label = tk.Label(self.drop_frame, text="将 .mid 或 .midi 文件拖入此区域",
                              font=("微软雅黑", 11), fg="#666")
        drop_label.pack(pady=20)
        
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        self.btn_convert = tk.Button(btn_frame, text="🔄 转换", command=self.convert_file,
                                     font=("微软雅黑", 11), bg="#4CAF50", fg="white",
                                     width=10, height=1, state=tk.DISABLED)
        self.btn_convert.pack(side=tk.LEFT, padx=3)
        
        self.btn_preview = tk.Button(btn_frame, text="🔊 试听", command=self.preview_sequence,
                                     font=("微软雅黑", 11), bg="#9C27B0", fg="white",
                                     width=10, height=1, state=tk.DISABLED)
        self.btn_preview.pack(side=tk.LEFT, padx=3)
        
        self.btn_stop_preview = tk.Button(btn_frame, text="⏹️ 停止试听", command=self.stop_preview,
                                          font=("微软雅黑", 11), bg="#F44336", fg="white",
                                          width=10, height=1, state=tk.DISABLED)
        self.btn_stop_preview.pack(side=tk.LEFT, padx=3)
        
        self.btn_save = tk.Button(btn_frame, text="💾 保存", command=self.save_result,
                                  font=("微软雅黑", 11), bg="#2196F3", fg="white",
                                  width=10, height=1, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=3)
        
        self.btn_run = tk.Button(btn_frame, text="🚀 运行", command=self.run_sequence,
                                 font=("微软雅黑", 11), bg="#FF9800", fg="white",
                                 width=10, height=1, state=tk.DISABLED)
        self.btn_run.pack(side=tk.LEFT, padx=3)
        
        self.btn_clear = tk.Button(btn_frame, text="🗑️ 清空", command=self.clear_all,
                                   font=("微软雅黑", 11), width=10, height=1)
        self.btn_clear.pack(side=tk.LEFT, padx=3)
        
        log_frame = tk.LabelFrame(self.root, text="📋 系统日志（包含 print 输出）", 
                                  font=("微软雅黑", 10))
        log_frame.pack(pady=10, padx=20, fill=tk.X)
        
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
        
        status_frame = tk.LabelFrame(self.root, text="📊 转换状态", 
                                     font=("微软雅黑", 10))
        status_frame.pack(pady=10, padx=20, fill=tk.X)
        
        self.status_text = scrolledtext.ScrolledText(status_frame, font=("Consolas", 10),
                                                      height=6, wrap=tk.WORD)
        self.status_text.pack(pady=5, padx=5, fill=tk.X)
        self.status_text.config(state=tk.DISABLED)
        
        preview_label = tk.Label(self.root, text="📋 转换结果预览 (前200个元素)",
                                 font=("微软雅黑", 10, "bold"))
        preview_label.pack(anchor=tk.W, padx=20)
        
        self.preview_text = scrolledtext.ScrolledText(self.root, font=("Consolas", 10),
                                                       height=10, wrap=tk.WORD)
        self.preview_text.pack(pady=5, padx=20, fill=tk.BOTH, expand=True)
        self.preview_text.config(state=tk.DISABLED)
        
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
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        if len(message) < 60:
            self.update_status(message[:60])
    
    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log("🗑️ 日志已清空")
    
    def set_status(self, message):
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(1.0, message)
        self.status_text.config(state=tk.DISABLED)
        self.status_text.see(tk.END)
    
    def append_status(self, message):
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
        
        # ===== 读取轨道信息 =====
        tracks = get_midi_tracks(file_path)
        if tracks:
            track_options = ["全部"]
            for idx, name, count in tracks:
                track_options.append(f"{idx+1}: {name} ({count}个音符)")
            self.track_combobox['values'] = track_options
            self.track_combobox.set(track_options[0])
            self.log(f"🎵 检测到 {len(tracks)} 个有音符的轨道")
            for idx, name, count in tracks:
                self.log(f"  轨道 {idx+1}: {name} ({count}个音符)")
        else:
            self.track_combobox['values'] = ["全部"]
            self.track_combobox.set("全部")
            self.log("⚠️ 未检测到有音符的轨道")
        
        self.convert_file()
    
    def convert_file(self):
        if not self.current_file:
            return
        
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.btn_preview.config(state=tk.DISABLED)
        self.btn_stop_preview.config(state=tk.DISABLED)
        self.update_status("正在转换...")
        self.log("🔄 开始转换...")
        
        take_highest = self.take_highest_var.get()
        auto_map = self.auto_map_var.get()
        spacing = self.spacing_var.get()
        max_jump = self.max_jump_var.get()
        
        # ===== 解析选中的轨道 =====
        track_selection = self.track_var.get()
        selected_track = None
        if track_selection != "全部":
            try:
                track_idx = int(track_selection.split(":")[0]) - 1
                selected_track = track_idx
            except:
                selected_track = None
        
        def do_convert():
            sequence, mapping_info, status = midi_to_sequence(
                self.current_file, 
                take_highest=take_highest,
                auto_map_sharp=auto_map,
                spacing=spacing,
                max_jump=max_jump,
                selected_track=selected_track
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
            self.btn_preview.config(state=tk.NORMAL)
            self.update_status(f"✅ 转换完成！共 {len(sequence)} 个元素")
            self.log(f"✅ 转换完成，共 {len(sequence)} 个音符元素")
        else:
            self.set_preview("❌ 转换失败，未生成有效音符")
            self.btn_save.config(state=tk.DISABLED)
            self.btn_run.config(state=tk.DISABLED)
            self.btn_preview.config(state=tk.DISABLED)
            self.update_status("❌ 转换失败")
            self.log("❌ 转换失败")
        
        self.btn_convert.config(state=tk.NORMAL)
    
    def preview_sequence(self):
        if not self.result_sequence:
            messagebox.showwarning("警告", "请先转换 MIDI 文件！")
            return
        
        self.preview_stop_event = threading.Event()
        self.btn_stop_preview.config(state=tk.NORMAL)
        self.btn_preview.config(state=tk.DISABLED)
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.log("🔊 开始试听...")
        self.update_status("试听中...")
        
        def do_preview():
            try:
                sequence = self.result_sequence
                play_preview(sequence, duration=80, stop_event=self.preview_stop_event)
                self.root.after(0, lambda: self.log("🔊 试听完成"))
                self.root.after(0, lambda: self.update_status("试听完成"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ 试听出错: {e}"))
                self.root.after(0, lambda: self.update_status("试听出错"))
            finally:
                self.root.after(0, lambda: self.btn_stop_preview.config(state=tk.DISABLED))
                self.root.after(0, lambda: self.btn_preview.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.btn_convert.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.btn_run.config(state=tk.NORMAL))
                self.preview_stop_event = None
        
        threading.Thread(target=do_preview, daemon=True).start()
    
    def stop_preview(self):
        if self.preview_stop_event:
            self.preview_stop_event.set()
            self.log("⏹️ 正在停止试听...")
            self.btn_stop_preview.config(state=tk.DISABLED)
    
    def run_sequence(self):
        if not self.result_sequence:
            messagebox.showwarning("警告", "请先转换 MIDI 文件！")
            return
        
        note_list = self.result_sequence
        stop_key = get_stop_key()
        self.log(f"🚀 开始运行程序，共 {len(note_list)} 个元素")
        self.log(f"⌨️ 按 {stop_key.upper()} 键可随时停止")
        self.update_status("运行中...")
        self.btn_run.config(state=tk.DISABLED)
        self.btn_preview.config(state=tk.DISABLED)
        
        def do_run():
            try:
                run_start(note_list, stop_key)
                
                self.root.after(0, lambda: self.log("✅ 程序执行完成！"))
                self.root.after(0, lambda: self.update_status("执行完成"))
                
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ 运行出错: {e}"))
                self.root.after(0, lambda: self.update_status("运行出错"))
            finally:
                self.root.after(0, lambda: self.btn_run.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.btn_preview.config(state=tk.NORMAL))
        
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
        if self.preview_stop_event:
            self.preview_stop_event.set()
            self.preview_stop_event = None
        
        self.current_file = None
        self.result_sequence = None
        self.mapping_info = None
        self.path_var.set("")
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.btn_preview.config(state=tk.DISABLED)
        self.btn_stop_preview.config(state=tk.DISABLED)
        self.track_combobox.set("全部")
        self.track_combobox['values'] = ["全部"]
        self.set_preview("")
        self.set_status("")
        self.log("🗑️ 已清空所有数据")
        self.update_status("就绪")
    
    def on_closing(self):
        if self.preview_stop_event:
            self.preview_stop_event.set()
        sys.stdout = self.original_stdout
        self.root.destroy()


def run_start(commond_list, stop_key='b'):
    import time
    import pydirectinput
    import pyperclip
    from pynput.keyboard import Key, Controller, Listener
    import ctypes

    stop_flag = False

    def on_press(key):
        nonlocal stop_flag
        try:
            if hasattr(key, 'char') and key.char and key.char.lower() == stop_key.lower():
                print(f"⏹️ 检测到 {stop_key.upper()} 键，正在停止...")
                stop_flag = True
                return False
            elif hasattr(key, 'name') and key.name.lower() == stop_key.lower():
                print(f"⏹️ 检测到 {stop_key.upper()} 键，正在停止...")
                stop_flag = True
                return False
        except Exception:
            pass
        return True

    def start():
        print(f'准备时间(5s),请快速调至游戏窗口')
        print(f'💡 按 {stop_key.upper()} 键可随时停止运行')
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

    def make_action(func):
        def wrapper():
            if not stop_flag:
                func()
        return wrapper

    @make_action
    def t1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('1')
        pydirectinput.click(button='right')

    @make_action
    def l1():
        pyperclip.copy('/tp ~ ~ ~1')
        pydirectinput.press('t')
        pydirectinput.keyDown('ctrl')
        pydirectinput.press('v')
        pydirectinput.keyUp('ctrl')
        pydirectinput.press('enter')
        pydirectinput.press('2')
        pydirectinput.click(button='right')

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    @make_action
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

    action_map = {
        't1': t1,
        'l1': l1, 'l2': l2, 'l3': l3, 'l4': l4, 'l5': l5, 'l6': l6, 'l7': l7,
        'm1': m1, 'm2': m2, 'm3': m3, 'm4': m4, 'm5': m5, 'm6': m6, 'm7': m7,
        'h1': h1, 'h2': h2, 'h3': h3, 'h4': h4, 'h5': h5, 'h6': h6, 'h7': h7,
    }

    print("检测到程序开始")

    listener = Listener(on_press=on_press)
    listener.daemon = True
    listener.start()

    start()

    for item in commond_list:
        if stop_flag:
            print(f"⏹️ 已停止，剩余 {len(commond_list) - commond_list.index(item)} 个指令未执行")
            break
        func = action_map.get(item)
        if func:
            func()
        else:
            print(f"⚠️ 未知指令: {item}")

    if stop_flag:
        print("⏹️ 程序已由用户终止")


if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    
    app = MidiToNoteGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()