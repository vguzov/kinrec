from functools import partial
import logging
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
        self._controller = None
        self.number_of_kinects = number_of_kinects

        # Variables to store state of the system
        self._state_template_kinect = "Status: {}\nFree space: {:03d} GB\nBatt. power: {:03d}%"
        self._state_template_server = "Status: {}"
        self._recorders = [{
            "state": RecorderState(),
            "button": None,
            "label": None
        } for _ in range(self.number_of_kinects)]
        self._state_server = "offline"
        self._params_kinect: KinectParams = KinectParams()

        # Initialize variables
        self._init_view_state()

        # Initialize pre-set styles for buttons
        self._init_button_styles()

        # Add menus and frames
        self._add_top_bar_menu()
        self._add_preview_frame()
        self._add_records_browser_frame()
        self._add_params_frame()
        self._add_recording_frame()
        self._add_state_frame()

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

    def _init_view_state(self):
        self.state = {
            "kinect": {
                "rgb_res": tk.StringVar(value=list(self._params_kinect._rgb_res_str2val)[0]),
                "depth_mode": tk.StringVar(value=list(self._params_kinect._depth_mode_str2val)[0]),
                "fps": tk.IntVar(value=self._params_kinect._fps_range[0]),
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
                "checkboxes": dict()
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
        # self.menubar = FocusLabelFrame(self, bd=1)
        # self.menubar.grid(row=0, column=0, columnspan=2, sticky="new")
        # # self.menubar.pack(side=tk.TOP, fill='x')
        #
        # button = FocusButton(self.menubar, text='About', command=self._callback_about)
        # # button.pack(side=tk.LEFT)
        # button = FocusButton(self.menubar, text='Exit', command=self.master.quit)
        # # button.pack(side=tk.LEFT)
        self.menubar = tk.Menu(self.parent)

        self.menubar.add_command(label='About', command=self._callback_about)
        self.menubar.add_command(label='Exit', command=self.master.quit)

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
        self.browser_frame = FocusLabelFrame(self, text="Browse recordings")
        self.browser_frame.rowconfigure(0, weight=1)
        self.browser_frame.columnconfigure(0, weight=1)

        # Subframe with records list and scrollbar
        # subframe creation
        browser_records_subframe = FocusLabelFrame(self.browser_frame, text="List")
        browser_records_subframe.grid_rowconfigure(0, weight=1)
        browser_records_subframe.grid_columnconfigure(0, weight=1)
        browser_records_subframe.grid_propagate(False)
        browser_records_subframe.grid(row=0, column=0, padx=5, pady=5)
        # canvas that holds records subsubframe and scrollbar
        browser_records_canvas = tk.Canvas(browser_records_subframe)
        browser_records_canvas.grid(row=0, column=0, sticky="news")
        # subsubframe
        self.browser_records_subsubframe = FocusLabelFrame(browser_records_canvas, bg="white")
        browser_records_canvas.create_window((0, 0), window=self.browser_records_subsubframe, anchor='nw')
        # browser_records_subsubframe.grid(row=0, column=0)
        # header for records list in subsubframe
        self.browser_records_database = dict()
        header = [
            tk.Label(self.browser_records_subsubframe, text="Collect?"),
            tk.Label(self.browser_records_subsubframe, text="Date"),
            tk.Label(self.browser_records_subsubframe, text="Name"),
            tk.Label(self.browser_records_subsubframe, text="Length"),
            tk.Label(self.browser_records_subsubframe, text="Params"),
            tk.Label(self.browser_records_subsubframe, text="Size"),
            tk.Label(self.browser_records_subsubframe, text="Status")
        ]
        for index, label in enumerate(header):
            label.grid(row=0, column=index, padx=2, sticky='news')
        self.browser_records_database[-1] = header
        # scrollbar
        records_scrollbar = tk.Scrollbar(
            browser_records_subframe, orient="vertical", command=browser_records_canvas.yview
        )
        records_scrollbar.grid(row=0, column=1, sticky='ns')
        browser_records_canvas.configure(yscrollcommand=records_scrollbar.set)
        # resize canvas to fit everything
        self.browser_records_subsubframe.update_idletasks()
        _width = 1.3 * sum([header[j].winfo_width() for j in range(len(header))])
        _height = 10 * header[0].winfo_height()
        browser_records_subframe.config(width=_width + records_scrollbar.winfo_width(), height=_height)
        browser_records_canvas.config(scrollregion=browser_records_canvas.bbox("all"))

        # Subframe with download button and progressbar
        browser_progress_subframe = FocusLabelFrame(self.browser_frame, text="Collection")
        browser_progress_subframe.grid(row=1, column=0)
        FocusButton(browser_progress_subframe, text='Collect!', width=7,
                    command=self._callback_records_collect).grid(row=0, column=0, padx=5, pady=5)

        self.browser_frame.grid(row=1, rowspan=3, column=2, sticky="ne", padx=5, pady=5)
        self.browser_frame.grid_remove()

    def _add_params_frame(self):
        self.params_frame = FocusLabelFrame(self, text="Recording parameters")
        self.params_frame.grid(row=1, column=1, padx=5, pady=5, sticky='e')
        # self.params_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        root = self.params_frame

        self.params_frame_fields = []
        # Row 0
        tk.Label(root, text="RGB resolution (H x W)").grid(row=0, column=0, columnspan=2, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["rgb_res"],
                             *list(self._params_kinect._rgb_res_str2val), command=self._callback_rgb_res)
        menu.config(width=12)
        menu.grid(row=0, column=2, padx=5, sticky='e')
        self.apply_params_button = FocusButton(root, text='Apply', width=10, style="KinectParams_Apply.TButton",
                                               command=self._callback_apply_params)
        self.apply_params_button.grid(row=0, rowspan=3, column=4, padx=5, ipady=20)
        # Row 1
        tk.Label(root, text="Depth mode").grid(row=1, column=0, columnspan=1, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["depth_mode"],
                             *list(self._params_kinect._depth_mode_str2val), command=self._callback_depth_mode)
        menu.config(width=25)
        menu.grid(row=1, column=1, columnspan=2, padx=5, sticky='e')
        # Row 2
        tk.Label(root, text="FPS").grid(row=2, column=0, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["fps"],
                             *list(self._params_kinect._fps_range), command=self._callback_fps)
        menu.config(width=3)
        menu.grid(row=2, column=1, padx=5, sticky='w')
        FocusCheckButton(root, text=' Synchronize', command=self._callback_sync,
                         variable=self.state['kinect']['sync']).grid(row=2, column=2, padx=5, sticky='e')

    # TODO change entries to BoundedNumericalEntry
    def _add_recording_frame(self):
        self.recording_frame = FocusLabelFrame(self, text="Recording")
        self.recording_frame.grid(row=2, column=1, padx=5, pady=5)
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

    def _add_state_frame(self):
        self.state_frame = FocusLabelFrame(self, text="State")
        self.state_frame.grid(row=3, column=1, padx=5, pady=5)
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

    def add_records_browser_row(self, id: int, entry: RecordsEntry):
        # create variable for checkbox
        self.state["recordings_list"]["checkboxes"][id] = tk.BooleanVar(value=False)

        date_str = datetime.fromtimestamp(entry.date).strftime("%d.%m.%Y, %H:%M")
        time_str = timedelta(seconds=entry.length)
        params_str = "\n".join([f"{k}: {v}" for k, v in entry.params.to_dict().items()])
        row = [
            FocusCheckButton(self.browser_records_subsubframe, text="",
                             command=partial(self._callback_select_recording, id),
                             variable=self.state["recordings_list"]["checkboxes"][id]),
            tk.Label(self.browser_records_subsubframe, text=f"{date_str}"),
            tk.Label(self.browser_records_subsubframe, text="Name"),
            tk.Label(self.browser_records_subsubframe, text=f"{time_str}"),
            tk.Label(self.browser_records_subsubframe, text=f"{params_str}"),
            tk.Label(self.browser_records_subsubframe, text=f"{entry.size:06.1f}"),
            tk.Label(self.browser_records_subsubframe, text=f"{entry.status}")
        ]
        return row

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
            state.status, state.free_space, state.bat_power
        ))

    # TODO rename to apply_kinect_params_reply
    # TODO change params to kinect_params elsewhere
    # TODO add freeze and unfreeze via params
    def params_apply_finalize(self, result: bool):
        if result:
            # save new default kinect parameters
            self._params_kinect = self._get_kinect_params_from_view()
            self.add_destroyable_message("info", "Kinect params applied successfully!")
        else:
            # update params to previous values
            self._update_kinect_params_view(self._params_kinect)
            self.add_destroyable_message("warning", "Kinect params were NOT applied!")
        self._update_apply_button_state(state="applied")

    def kinect_params_init(self, params: KinectParams):
        self._params_kinect = params
        self._update_kinect_params_view(params)

    def start_recording_reply(self):
        # TODO add timer
        # Change internal flag
        self.state["recording"]["is_on"].set(value=True)
        # Set status frame
        name = self.state["recording"]["name"].get()
        self.recording_status_label.configure(text=f"Recording {name} in progress.")
        # Change button style
        self._update_recording_button_state(state="recording")

    def stop_recording(self):
        # Change internal flag
        self.state["recording"]["is_on"].set(value=False)
        # Set status frame
        self.state["recording"]["name"].set(value="")
        self.recording_status_label.configure(text="Press Record! to start recording")
        # Change button style
        self._update_recording_button_state(state="not recording")
        self._controller.stop_recording()

    def browse_recordings_reply(self, recordings_database: Dict[int, RecordsEntry]):
        for index, (recording_id, recording) in enumerate(recordings_database.items()):
            row = self.add_records_browser_row(recording_id, recording)
            for column, widget in enumerate(row):
                widget.grid(row=index, column=column, padx=2, sticky='news')
            self.browser_records_database[recording_id] = row
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
            for recording_id, row in self.browser_records_database.items():
                # except for header
                if recording_id != -1:
                    for widget in row:
                        widget.destroy()
            self.state["recordings_list"]["checkboxes"] = {}
        else:
            self.state["recordings_list"]["is_on"].set(True)
            self.browser_frame.grid()
            self.recording_browse_button.configure(text="Close\nbrowser")
            # TODO move to a separate button
            self._controller.collect_recordings_info()

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
            pass
        else:
            # recording is not in progress
            name = self.state["recording"]["name"].get()
            duration = int(self.state["recording"]["duration"].get())
            delay = int(self.state["recording"]["delay"].get())
            self._update_recording_button_state(state="waiting")

            self._controller.start_recording(name, duration, delay)

    def _callback_select_recording(self, recording_id: int):
        pass

    def _callback_records_collect(self):
        recording_ids_to_collect = []
        for recording_id, variable in self.state["recordings_list"]["checkboxes"].items():
            if variable.get():
                recording_ids_to_collect.append(recording_id)
        # TODO add controller collect records call

    def _callback_about(self):
        self.menubar.focus_set()

        text = [
            "Developed by:",
            "Ilya Petrov and Vladimir Guzov",
            # "License, 2021"
        ]

        messagebox.showinfo("About Demo", '\n'.join(text))

    # ==================================================================================================================

    def _update_kinect_params_view(self, params: KinectParams):
        self.state["kinect"]["rgb_res"].set(value=self._params_kinect._rgb_res_val2str[params.rgb_res])
        self.state["kinect"]["depth_mode"].set(value=self._params_kinect._depth_mode_val2str[(params.depth_wfov , params.depth_binned)])
        self.state["kinect"]["fps"].set(value=params.fps)
        self.state["kinect"]["sync"].set(value=params.sync)

    def _get_kinect_params_from_view(self):
        params_state = self.state["kinect"]
        rgb_res = self._params_kinect._rgb_res_str2val[params_state["rgb_res"].get()]
        wfov, binned = self._params_kinect._depth_mode_str2val[params_state["depth_mode"].get()]
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
            kinect_id = self._recorders[recorder_index]["state"].kinect_id
            if preview_is_on:
                if recorder_index == preview_recorder_index:
                    self._recorders[recorder_index]["button"].configure(text=f"Kinect id {kinect_id}\n(stop preview)",
                                                                        state=tk.NORMAL)
                else:
                    self._recorders[recorder_index]["button"].configure(state=tk.DISABLED)
            else:
                self._recorders[recorder_index]["button"].configure(text=f"Kinect id {kinect_id}\n(launch preview)",
                                                                    state=tk.NORMAL)
