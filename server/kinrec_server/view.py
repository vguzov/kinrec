import math
from functools import partial
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict

import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from PIL import Image, ImageTk

from .internal import RecorderState, RecordsEntry, KinectParams
from .tk_wrappers import FocusButton, FocusCheckButton, FocusLabelFrame

logger = logging.getLogger("KRS.view")


class KinRecView(ttk.Frame):
    def __init__(self, parent, number_of_kinects=4):
        super().__init__(parent)
        self._preview_frame_size = (800, 400)
        self.parent = parent
        self.pack(fill="both", expand=True)
        self.columnconfigure(2, weight=1)  # 2 is the column with the RecordsBrowser
        self.rowconfigure((1,2), weight=1)  # Make RecordsBrowser resizable
        self._controller = None
        self.number_of_kinects = number_of_kinects

        # Variables to store state of the system
        self._state_template_kinect = "Status: {}\nFree space: {:03d} GB\nBatt. power: {:03d}%{:s}"
        self._state_template_server = "Status: {}"
        self._recorders = [{
            "state": RecorderState(),
            "button": None,
            "label": None
        } for _ in range(self.number_of_kinects)]
        self._state_server = "offline"
        self.kinect_params: KinectParams = KinectParams()

        # Initialize variables
        self._init_view_state()

        # Initialize pre-set styles for buttons
        self._init_button_styles()

        # Add menus and frames
        self._add_top_bar_menu()
        self._add_preview_frame()
        self._add_records_browser_frame()
        self._add_left_column_frame()
        self._add_params_frame(parent=self.left_column_frame)
        self._add_recording_frame(parent=self.left_column_frame)
        self._add_state_frame(parent=self.left_column_frame)

        # # Pre-defined constants
        # self.RET_CODE_EXIT, self.RET_CODE_OK, self.RET_CODE_ERROR = -1, 0, 1
        # # State messages for state table
        # self._state_message_server = "Status: {}"
        # self._state_server_key = "_state_server_"
        # self._state_message_kinect = "Status: {}\n\nFree space: {:04d} GB\n\nBattery power: {:03d}%"
        # self._state_kinect_key = "_state_kinect_{:02d}_"
        #
        # params_frame = self._create_params_frame()
        # recording_frame = self._create_recording_frame()
        # state_table = self._create_state_table()
        #
        # self.layout = [
        #     [params_frame],
        #     [recording_frame],
        #     [state_table]
        # ]
        #
        # self.window = sg.Window("Kinect Recorder GUI", self.layout, resizable=True)
        self._browser_size = (1000, 300 + self.number_of_kinects * 50)
        
    def _init_view_state(self):
        self.state = {
            "kinect": {
                "rgb_res": tk.StringVar(value=list(self.kinect_params._rgb_res_str2val)[0]),
                "depth_mode": tk.StringVar(value=list(self.kinect_params._depth_mode_str2val)[0]),
                "fps": tk.IntVar(value=self.kinect_params._fps_range[0]),
                "sync": tk.BooleanVar(value=False),
            },
            "recording": {
                "is_on": tk.BooleanVar(value=False),
                "name": tk.StringVar(value=""),
                "duration": tk.StringVar(value="-1"),
                "delay": tk.StringVar(value="0")
                #"duration": tk.IntVar(value=-1),
                #"delay": tk.IntVar(value=-0)
            },
            "recordings_list": {
                "is_on": tk.BooleanVar(value=False),
            },
            "preview": {
                "is_on": tk.BooleanVar(value=False),
                "recorder_index": tk.IntVar(value=-1)
            }
        }

    def _init_button_styles(self):
        s = ttk.Style()
        s.configure("KinectParams_Apply.TButton", background="green", foreground="black", height=6)
        s.configure("Recording_Record.TButton", background="red", foreground="black", height=6)
        s.configure("Recording_Stop.TButton", background="grey", foreground="black", height=6)
        s.configure("InProgress.TButton", background="yellow", foreground="black", height=6)

    # ============================================= Configuring GUI Layout =============================================
    def _add_top_bar_menu(self):
        self.menubar = tk.Menu(self.parent)

        self.menubar.add_command(label='Relaunch', command=self._callback_relaunch)
        self.menubar.add_command(label='Reboot', command=self._callback_reboot)
        self.menubar.add_command(label='Shutdown', command=self._callback_shutdown)
        self.menubar.add_command(label='About', command=self._callback_about)
        self.menubar.add_command(label='Exit', command=self._callback_exit)

        self.parent.config(menu=self.menubar)

    def _add_preview_frame(self):
        self.preview_frame = FocusLabelFrame(self, text="Preview")
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(self.preview_frame, highlightthickness=0, cursor="hand1",
                                        width=self._preview_frame_size[0], height=self._preview_frame_size[1])
        self.preview_image = None
        self.preview_canvas.grid(row=0, column=0, sticky='nw', padx=5, pady=5)

        # self.preview_frame.pack(side=tk.LEFT, fill="both", expand=True, padx=5, pady=5)
        self.preview_frame.grid(row=1, rowspan=3, column=0, sticky="ne", padx=5, pady=5)
        self.preview_frame.grid_remove()

    def _add_records_browser_frame(self):
        # Local function for sorting the treeview column-wise
        def _browser_sort_column(treeview, column, reverse):
            l = [(treeview.set(k, column), k) for k in treeview.get_children('')]
            l.sort(reverse=reverse)

            # rearrange items in sorted positions
            for index, (val, k) in enumerate(l):
                treeview.move(k, '', index)

            # reverse sort next time
            treeview.heading(
                column, command=lambda _column=column: \
                _browser_sort_column(treeview, _column, not reverse)
            )
        
        # Main frame that holds everything
        self.browser_frame = FocusLabelFrame(self, text="Browse recordings")
        self.browser_frame.rowconfigure((0, 1), weight=1)
        self.browser_frame.columnconfigure(0, weight=1)

        # Create TreeView with vertical Scrollbar
        # TODO add params?
        columns = ["date", "name", "length", "size", "status"]
        self.browser_frame_tree = ttk.Treeview(self.browser_frame, show="headings", columns=columns)
        vsb = ttk.Scrollbar(self.browser_frame, orient="vertical", command=self.browser_frame_tree.yview)
        self.browser_frame_tree.configure(yscrollcommand=vsb.set)
        self.browser_frame_tree.grid(row=0, rowspan=2, column=0, sticky='news', padx=5, pady=5)
        vsb.grid(row=0, rowspan=2, column=1, sticky='nws', pady=5)

        # Set initial column widths
        self.browser_frame_tree.column("date", width=120)
        self.browser_frame_tree.column("name", width=100)
        self.browser_frame_tree.column("length", width=70)
        self.browser_frame_tree.column("size", width=50)
        self.browser_frame_tree.column("status", width=70)

        # Add sorting to columns
        for column in columns:
            self.browser_frame_tree.heading(
                column, text=column.capitalize(), command=lambda _column=column: \
                _browser_sort_column(self.browser_frame_tree, _column, False)
            )
        
        # Subframe with download button and progressbar
        browser_progress_subframe = FocusLabelFrame(self.browser_frame, text="Collection")
        browser_progress_subframe.grid(row=2, column=0, columnspan=2, sticky="ns")
        FocusButton(browser_progress_subframe, text='Collect!', width=7,
                    command=self._callback_records_collect).grid(row=0, column=0, padx=5, pady=5)
        FocusButton(browser_progress_subframe, text='Delete', width=7,
                    command=self._callback_records_verify_delete).grid(row=0, column=1, padx=5, pady=5)

        self.browser_frame.grid(row=1, rowspan=2, column=2, sticky="news", padx=5, pady=5)
        self.browser_frame.grid_remove()

    def _add_left_column_frame(self):
        self.left_column_frame = FocusLabelFrame(self, borderwidth=0)
        self.left_column_frame.grid(row=1, column=0, sticky="n")


    def _add_params_frame(self, parent):
        self.params_frame = FocusLabelFrame(parent, text="Recording parameters")
        self.params_frame.grid(row=0, column=0, padx=5, pady=5, sticky='n')
        root = self.params_frame

        self.params_frame_fields = []
        # Row 0
        tk.Label(root, text="RGB resolution (H x W)").grid(row=0, column=0, columnspan=2, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["rgb_res"],
                             *list(self.kinect_params._rgb_res_str2val), command=self._callback_rgb_res)
        menu.config(width=12)
        menu.grid(row=0, column=2, padx=5, sticky='e')
        self.apply_params_button = FocusButton(root, text='Apply', width=10, style="KinectParams_Apply.TButton",
                                               command=self._callback_apply_params)
        self.apply_params_button.grid(row=0, rowspan=3, column=4, padx=5, ipady=20)
        # Row 1
        tk.Label(root, text="Depth mode").grid(row=1, column=0, columnspan=1, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["depth_mode"],
                             *list(self.kinect_params._depth_mode_str2val), command=self._callback_depth_mode)
        menu.config(width=25)
        menu.grid(row=1, column=1, columnspan=2, padx=5, sticky='e')
        # Row 2
        tk.Label(root, text="FPS").grid(row=2, column=0, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["fps"],
                             *list(self.kinect_params._fps_range), command=self._callback_fps)
        menu.config(width=3)
        menu.grid(row=2, column=1, padx=5, sticky='w')
        FocusCheckButton(root, text=' Synchronize', command=self._callback_sync,
                         variable=self.state['kinect']['sync']).grid(row=2, column=2, padx=5, sticky='e')

    # TODO change entries to BoundedNumericalEntry
    def _add_recording_frame(self, parent):
        self.recording_frame = FocusLabelFrame(parent, text="Recording")
        self.recording_frame.grid(row=1, column=0, sticky='n', padx=5, pady=5)
        root = self.recording_frame

        # Row 0
        tk.Label(root, text="Name: ").grid(row=0, column=0, padx=5, pady=1, sticky='ew')
        self.recording_name = tk.Entry(root, textvariable=self.state["recording"]["name"], width=20)
        self.recording_name.grid(row=0, column=1, columnspan=2, padx=5, pady=1, sticky='ew')
        # Row 1
        tk.Label(root, text="Duration (sec.): ").grid(row=1, column=0, columnspan=2, padx=5, pady=1, sticky='ew')
        self.recording_duration = tk.Entry(root, textvariable=self.state["recording"]["duration"], width=5)
        self.recording_duration.grid(row=1, column=2, padx=5, pady=1, sticky='ew')
        # Row 2
        tk.Label(root, text="Delay (sec.): ").grid(row=2, column=0, columnspan=2, padx=5, pady=1, sticky='ew')
        self.recording_duration = tk.Entry(root, textvariable=self.state["recording"]["delay"], width=5)
        self.recording_duration.grid(row=2, column=2, padx=5, pady=1, sticky='ew')
        # Row 3
        self.recording_status_label = tk.Label(
            root, text="Press Record! to start recording", width=35
        )
        self.recording_status_label.grid(row=3, column=0, columnspan=3, padx=5, pady=1, sticky='ew')
        # Side button 1
        self.recording_start_button = FocusButton(
            root, text='Record!', width=10, command=self._callback_start_recording, style="Recording_Record.TButton",
        )
        self.recording_start_button.grid(row=0, rowspan=2, column=4, padx=5, pady=5)
        # Side button 2
        self.recording_browse_button = FocusButton(
            root, text='Browse\nrecordings', width=10, command=self._callback_browse_recordings
        )
        self.recording_browse_button.grid(row=2, rowspan=2, column=4, padx=5, pady=5)

    def _add_state_frame(self, parent):
        self.state_frame = FocusLabelFrame(parent, text="State")
        self.state_frame.grid(row=2, column=0, sticky='n', padx=5, pady=5)
        # self.state_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        root = self.state_frame
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(3, weight=1)
        # Row 1
        tk.Label(root, text="Device").grid(row=0, column=1, padx=5, pady=1, sticky='ew')
        tk.Label(root, text="State").grid(row=0, column=2, padx=10, pady=1, sticky='ew')
        ttk.Separator(root, orient="horizontal").grid(column=1, columnspan=2, sticky='ew')
        # Row 2
        tk.Label(root, text="Server").grid(row=2, column=1, padx=5, pady=1, sticky='ew')
        self._state_server_label = tk.Label(
            root, text=self._state_template_server.format(self._state_server)
        )
        self._state_server_label.grid(row=2, column=2, padx=10, pady=1, sticky='w')

        # Other rows
        for recorder_index in range(self.number_of_kinects):
            # TODO default state tk.DISABLED
            # TODO add sorting based on kinect_id
            self._recorders[recorder_index]["button"] = FocusButton(root, text="",
                                                                    command=partial(self._callback_preview,
                                                                                    recorder_index))
            self._recorders[recorder_index]["button"].grid(row=3 + recorder_index, column=1, padx=5, pady=1,
                                                           sticky='ew')

            self._recorders[recorder_index]["label"] = tk.Label(root, justify=tk.LEFT, text="")
            self._recorders[recorder_index]["label"].grid(row=3 + recorder_index, column=2, padx=10, pady=1, sticky='w')

            self.update_recorder_state(recorder_index, self._recorders[recorder_index]["state"])

    @staticmethod
    def add_destroyable_message(type, text, duration=2000):
        assert type in ["info", "warning", "error"], f'type must be in ["info", "warning", "error"], got: {type}'
        tmp_window = tk.Tk()
        tmp_window.withdraw()

        try:
            tmp_window.after(duration, tmp_window.destroy)
            if type == "info":
                response = tk.messagebox.showinfo(master=tmp_window, title=type, message=text)
            elif type == "warning":
                response = tk.messagebox.showwarning(master=tmp_window, title=type, message=text)
            else:
                response = tk.messagebox.showerror(master=tmp_window, title=type, message=text)

            if response:
                tmp_window.destroy()
        except tk.TclError:
            pass
    # ==================================================================================================================

    # =============================================== External Interfaces ==============================================
    @property
    def preview_frame_size(self):
        return self._preview_frame_size

    def set_controller(self, controller):
        self._controller = controller

    def start_preview(self, recorder_index):
        if self.state["preview"]["is_on"].get():
            logger.warning(f"Preview is already launched for recorder {self.state['preview']['recorder_index'].get()}")
        else:
            # preview is not launched
            self.state["preview"]["is_on"].set(True)
            self.state["preview"]["recorder_index"].set(recorder_index)
            self.preview_frame.grid()
            logger.info(f"launched preview for {recorder_index}")
        self._update_preview_buttons_state()

    def stop_preview(self, recorder_index):
        if self.state["preview"]["is_on"].get():
            if self.state["preview"]["recorder_index"].get() == recorder_index:
                self.preview_frame.grid_remove()
                self.state["preview"]["is_on"].set(False)
                self.state["preview"]["recorder_index"].set(-1)

                self.preview_canvas.delete("preview_iamge")
                self.preview_image = None

                logger.info(f"stopped preview for {recorder_index}")
            else:
                logger.warning(f"Can't stop preview for {recorder_index}, "
                               f"as it is launched for {self.state['preview']['recorder_index'].get()}")
        else:
            logger.warning("No preview is launched")

        self._update_preview_buttons_state()

    def set_preview_frame(self, frame):
        self.image_tk = ImageTk.PhotoImage(image=Image.fromarray(frame))
        if self.preview_image is None:
            self.preview_image = self.preview_canvas.create_image(
                0, 0, anchor="nw", image=self.image_tk, tag="preview_image"
            )
        else:
            self.preview_canvas.itemconfig(self.preview_image, image=self.image_tk)

    def update_progressbar(self):
        pass

    def update_server_state(self, status: str):
        if status == "offline":
            self._state_server = status
        elif status == "online":
            self._state_server = status
        else:
            raise ValueError(f"Unknown server status {status}")
        self._state_server_label["text"] = self._state_template_server.format(self._state_server)

    def update_recorder_state(self, recorder_index: int, state: RecorderState):
        # statuses: "offline", "ready", "preview", "recording", "kin. not ready"
        self._recorders[recorder_index]["state"] = state

        if state.status in ["offline", "kin. not ready"]:
            button_state = tk.DISABLED
            text = f"Kinect id {state.kinect_alias}\n(launch preview)"
        elif state.status == "preview":
            button_state = tk.NORMAL
            text = f"Kinect id {state.kinect_alias}\n(stop preview)"
        elif state.status == "recording":
            button_state = tk.DISABLED
            text = f"Kinect id {state.kinect_alias}\n(launch preview)"
        elif state.status == "ready":
            button_state = tk.NORMAL
            text = f"Kinect id {state.kinect_alias}\n(launch preview)"
        else:
            raise ValueError(f"Unknown recorder {recorder_index} status {state.status}")

        self._recorders[recorder_index]["button"].configure(text=text)
        self._recorders[recorder_index]["label"].configure(text=self._state_template_kinect.format(
            state.status, state.free_space, state.bat_power, ", Plugged" if state.bat_plugged else ""
        ))

    # TODO rename to apply_kinect_params_reply
    # TODO add freeze and unfreeze via params
    def params_apply_finalize(self, result: bool):
        if result:
            # save new default kinect parameters
            self.kinect_params = self._get_kinect_params_from_view()
            # self.add_destroyable_message("info", "Kinect params applied successfully!")
        else:
            # update params to previous values
            self._update_kinect_params_view(self.kinect_params)
            self.add_destroyable_message("warning", "Kinect params were NOT applied!")
        self._update_apply_button_state(state="applied")

    def kinect_params_init(self, params: KinectParams):
        self.kinect_params = params
        self._update_kinect_params_view(params)

    def start_recording_reply(self, is_successful=True):
        # TODO add timer
        if is_successful:
            # Change internal flag
            self.state["recording"]["is_on"].set(value=True)
            # Set status frame
            name = self.state["recording"]["name"].get()
            self.recording_status_label.configure(text=f"Recording {name} in progress.")
            # Change button style
            self._update_recording_button_state(state="recording")
        else:
            # Change button style
            self._update_recording_button_state(state="not recording")

    def stop_recording_reply(self):
        # Change internal flag
        self.state["recording"]["is_on"].set(value=False)
        # Set status frame
        self.state["recording"]["name"].set(value="")
        self.recording_status_label.configure(text="Press Record! to start recording")
        # Change button style
        self._update_recording_button_state(state="not recording")

    def browse_recordings_reply(self, recordings_database: Dict[int, RecordsEntry]):        
        for index, (recording_id, recording) in enumerate(recordings_database.items()):
            date_str = datetime.fromtimestamp(recording.date).strftime("%Y-%m-%d, %H:%M")
            if recording.length < 0:
                length_str = "N/A"
            else:
                length_str = timedelta(seconds=recording.length)
                length_str = timedelta(seconds=math.ceil(length_str.total_seconds()))
            params_str = "\n".join([f"{k}: {v}" for k, v in recording.params.to_dict().items()])
            size_str = f"{recording.size/2**20:6.1f} MB"

            self.browser_frame_tree.insert(
                "", "end", iid=str(recording_id),
                values=(date_str, recording.name, length_str, size_str, recording.status)
            )
    # ==================================================================================================================

    # ================================================ Button callbacks ================================================
    def _callback_apply_params(self):
        params = self._get_kinect_params_from_view()
        self._update_apply_button_state(state="in progress")
        self._controller.apply_kinect_params(params)

    def _callback_browse_recordings(self):
        if self.state["recordings_list"]["is_on"].get():
            self.state["recordings_list"]["is_on"].set(False)
            self.browser_frame.grid_remove()
            self.recording_browse_button.configure(text="Browse\nrecordings")
            # cleaning of old database
            self.browser_frame_tree.delete(*self.browser_frame_tree.get_children())
            # restore initial size
            self.parent.geometry("{}x{}".format(*self.parent._default_size))
        else:
            self.state["recordings_list"]["is_on"].set(True)
            self.browser_frame.grid()
            self.recording_browse_button.configure(text="Close\nbrowser")
            # TODO move to a separate button
            self._controller.collect_recordings_info()
            self.parent.geometry("{}x{}".format(*self._browser_size))

    def _callback_rgb_res(self, *args):
        self._update_apply_button_state(state="not applied")

    def _callback_depth_mode(self, *args):
        self._update_apply_button_state(state="not applied")

    def _callback_fps(self, *args):
        self._update_apply_button_state(state="not applied")

    def _callback_sync(self):
        self._update_apply_button_state(state="not applied")

    def _callback_preview(self, recorder_index):
        if self.state["preview"]["is_on"].get():
            # Stop preview
            self._controller.stop_preview(recorder_index)
        else:
            # Launch preview
            self._controller.start_preview(recorder_index)

    def _callback_start_recording(self):
        if self.state["recording"]["is_on"].get():
            # recording is in progress
            # self._update_recording_button_state(state="waiting")
            self._controller.stop_recording()
        else:
            # recording is not in progress
            name = self.state["recording"]["name"].get()
            duration = int(self.state["recording"]["duration"].get())
            delay = int(self.state["recording"]["delay"].get())
            self._update_recording_button_state(state="waiting")

            self._controller.start_recording(name, duration, delay)

    def _callback_records_collect(self):
        recording_ids_to_collect = list(self.browser_frame_tree.selection())
        recording_ids_to_collect = [int(i) for i in recording_ids_to_collect]

        if len(recording_ids_to_collect) == 0:
           self.add_destroyable_message("Warning", "No recordings selected")
        else:
            self._controller.collect_recordings(recording_ids_to_collect)

    def _callback_records_verify_delete(self):
        recording_ids_to_delete = list(self.browser_frame_tree.selection())
        recording_ids_to_delete = [int(i) for i in recording_ids_to_delete]
        n_recordings = len(recording_ids_to_delete)
        
        if n_recordings == 0:
            self.add_destroyable_message("Warning", "No recordings selected")
        else:
            msg_box = tk.messagebox.askquestion(
                'Records deletion', 
                f'Are you sure you want to delete the selected {n_recordings} recording(-s)?',
                icon='warning'
            )
            if msg_box == 'yes':
                self._controller.delete_recordings(recording_ids_to_delete)
                # update list after deletion
                self.browser_frame_tree.delete(*self.browser_frame_tree.get_children())
                self._controller.collect_recordings_info()
            else:
                pass

    def _callback_about(self):
        self.menubar.focus_set()

        text = [
            "Developed by:",
            "Ilya Petrov and Vladimir Guzov",
            # "License, 2021"
        ]

        messagebox.showinfo("About Demo", '\n'.join(text))

    def _callback_relaunch(self):
        pass

    def _callback_reboot(self):
        self._controller.reboot()

    def _callback_shutdown(self):
        self._controller.shutdown()

    def _callback_exit(self):
        # TODO check if warning can be escaped
        self.parent.destroy()
    # ==================================================================================================================

    def _update_kinect_params_view(self, params: KinectParams):
        self.state["kinect"]["rgb_res"].set(value=self.kinect_params._rgb_res_val2str[params.rgb_res])
        self.state["kinect"]["depth_mode"].set(value=self.kinect_params._depth_mode_val2str[(params.depth_wfov , params.depth_binned)])
        self.state["kinect"]["fps"].set(value=params.fps)
        self.state["kinect"]["sync"].set(value=params.sync)

    def _get_kinect_params_from_view(self):
        params_state = self.state["kinect"]
        rgb_res = self.kinect_params._rgb_res_str2val[params_state["rgb_res"].get()]
        wfov, binned = self.kinect_params._depth_mode_str2val[params_state["depth_mode"].get()]
        fps = params_state["fps"].get()
        sync = params_state["sync"].get()
        return KinectParams(rgb_res=rgb_res, depth_wfov=wfov, depth_binned=binned, fps=fps, sync=sync)

    def _update_apply_button_state(self, state: str):
        assert state in ["applied", "not applied", "in progress"], \
            f'state must be in ["applied", "not applied", "in progress"], got {state}'
        if state == "applied":
            self.apply_params_button.configure(text="Apply", style="KinectParams_Apply.TButton")
        elif state == "not applied":
            self.apply_params_button.configure(text="Unsaved\nchanges.\nApply", style="KinectParams_Apply.TButton")
        else:
            self.apply_params_button.configure(text="In Progress", style="InProgress.TButton")

    def _update_recording_button_state(self, state:str):
        assert state in ["recording", "not recording", "waiting"], \
            f'state must be in ["recording", "not recording", "waiting"], got {state}'
        if state == "recording":
            self.recording_start_button.configure(text="Stop", style="Recording_Stop.TButton")
        elif state == "not recording":
            self.recording_start_button.configure(text="Record!", style="Recording_Record.TButton")
        else:
            self.recording_start_button.configure(text="Waiting\ncontroller", style="InProgress.TButton")

    def _update_preview_buttons_state(self):
        preview_is_on = self.state["preview"]["is_on"].get()
        preview_recorder_index = self.state["preview"]["recorder_index"].get()

        for recorder_index in range(self.number_of_kinects):
            kinect_alias = self._recorders[recorder_index]["state"].kinect_alias
            if preview_is_on:
                if recorder_index == preview_recorder_index:
                    self._recorders[recorder_index]["button"].configure(text=f"Kinect id {kinect_alias}\n(stop preview)",
                                                                        state=tk.NORMAL)
                else:
                    self._recorders[recorder_index]["button"].configure(state=tk.DISABLED)
            else:
                self._recorders[recorder_index]["button"].configure(text=f"Kinect id {kinect_alias}\n(launch preview)",
                                                                    state=tk.NORMAL)
