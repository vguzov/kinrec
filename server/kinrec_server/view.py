from functools import partial

import tkinter as tk
from tkinter import messagebox, filedialog, ttk

from .internal import RecorderState
from .tk_wrappers import FocusButton, FocusCheckButton, FocusLabelFrame


class KinRecView(ttk.Frame):
    def __init__(self, parent, number_of_kinects=4):
        super().__init__(parent)
        self.parent = parent
        self.pack(fill="both", expand=True)
        self._controller = None
        self.number_of_kinects = 4

        # Constant parameters
        self._rgb_resolutions = {
            "1280x720": (1280, 720), "1920x1080": (1920, 1080), "2560x1440": (2560, 1440),
            "2048x1536": (2048, 1536), "3840x2160": (3840, 2160), "4096x3072": (4096, 3072)
        }
        self._depth_modes = {
            "WFOV unbinned (1024x1024)": (1024, 1024), "WFOV binned    (512x512)": (512, 512),
            "NFOV unbinned  (640x576)": (640, 576),   "NFOV binned    (320x288)": (320, 288)
        }
        self._fps = [5, 10, 15, 30]
        self._state_template_kinect = "Status: {}\nFree space: {:03d} GB\nBatt. power: {:03d}%"
        self._state_template_server = "Status: {}"
        self._state_kinects = self.number_of_kinects * [RecorderState()]
        self._state_kinect_buttons = []
        self._state_kinect_labels = []
        self._state_server = "offline"
        self._state_server_label = None

        # Styles for buttons
        s = ttk.Style()
        s.configure("Apply.TButton", background="green", foreground="black", height=6)

        # Initialize variables
        self._init_view_state()

        # Add menus and frames
        self._add_top_bar_menu()
        self._add_preview_canvas()
        self._add_records_browser_frame()
        self._add_params_frame()
        self._add_recording_frame()
        self._add_state_frame()

        # # Pre-defined constamts
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
                "rgb_res": tk.StringVar(value=list(self._rgb_resolutions)[0]),
                "depth_mode": tk.StringVar(value=list(self._depth_modes)[0]),
                "fps": tk.IntVar(value=self._fps[0]),
                "sync": tk.BooleanVar(value=False),
            },
            "recording": {

            },
            "preview": {
                "is_on": tk.BooleanVar(value=False),
                "kinect_index": tk.IntVar(value=-1)
            }
        }

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

    def _add_preview_canvas(self):
        self.preview_frame = FocusLabelFrame(self, text="Preview")
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)

        self._preview_canvas = tk.Canvas(self.preview_frame, highlightthickness=0, cursor="hand1", width=400, height=400)
        self._preview_canvas.grid(row=0, column=0, sticky='ns', padx=5, pady=5)

        # self.preview_frame.pack(side=tk.LEFT, fill="both", expand=True, padx=5, pady=5)
        self.preview_frame.grid(row=1, rowspan=3, column=0, sticky="ne", padx=5, pady=5)
        self.preview_frame.grid_remove()

    def _add_records_browser_frame(self):
        pass

    def _add_params_frame(self):
        self.params_frame = FocusLabelFrame(self, text="Recording parameters")
        self.params_frame.grid(row=1, column=1, padx=5, pady=5, sticky='e')
        # self.params_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        root = self.params_frame

        self.params_frame_fields = []
        # Row 0
        tk.Label(root, text="RGB resolution (H x W)").grid(row=0, column=0, columnspan=2, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["rgb_res"],
                             *list(self._rgb_resolutions), command=self._callback_rgb_res)
        menu.config(width=12)
        menu.grid(row=0, column=2, padx=5, sticky='e')
        FocusButton(root, text='Apply', width=5, style="Apply.TButton",
                    command=self._callback_apply_params).grid(row=0, rowspan=3, column=4, padx=5, ipady=20)
        # Row 1
        tk.Label(root, text="Depth mode").grid(row=1, column=0, columnspan=1, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["depth_mode"],
                             *list(self._depth_modes), command=self._callback_depth_mode)
        menu.config(width=25)
        menu.grid(row=1, column=1, columnspan=2, padx=5, sticky='e')
        # Row 2
        tk.Label(root, text="FPS").grid(row=2, column=0, padx=5, pady=1, sticky='w')
        menu = tk.OptionMenu(root, self.state["kinect"]["fps"],
                             *list(self._fps), command=self._callback_fps)
        menu.config(width=3)
        menu.grid(row=2, column=1, padx=5, sticky='w')
        FocusCheckButton(root, text=' Synchronize', command=self._callback_sync,
                         variable=self.state['kinect']['sync']).grid(row=2, column=2, padx=5, sticky='e')

    def _add_recording_frame(self):
        pass

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
        for kinect_index in range(self.number_of_kinects):
            button = FocusButton(root, text="Kinect id <None>\n(launch preview)",
                                command=partial(self._callback_preview, kinect_index))
            # TODO default state tk.DISABLED
            button.grid(row=3 + kinect_index, column=1, padx=5, pady=1, sticky='ew')
            self._state_kinect_buttons.append(button)

            state = tk.Label(
                root, justify=tk.LEFT, text=self._state_template_kinect.format(
                    self._state_kinects[kinect_index].status,
                    self._state_kinects[kinect_index].free_space,
                    self._state_kinects[kinect_index].bat_power
                )
            )
            state.grid(row=3 + kinect_index, column=2, padx=10, pady=1, sticky='w')
            self._state_kinect_labels.append(state)
    # ==================================================================================================================

    # =============================================== External Interfaces ==============================================
    def update_progressbar(self):
        pass

    def update_server_state(self):
        pass

    def update_recorder_state(self, index: int, state: RecorderState):
        # TODO change state of button based
        self._state_kinect_buttons[index].configure(text="Kinect id <None>\n(launch preview)")
    # ==================================================================================================================

    # ================================================ Button callbacks ================================================
    def _callback_apply_params(self):
        # update example
        # self._state_kinect_labels[1]['text'] = self._state_template_kinect.format("online", 300, 55)
        pass

    def _callback_rgb_res(self):
        pass

    def _callback_depth_mode(self):
        pass

    def _callback_fps(self):
        pass

    def _callback_sync(self):
        pass

    def _callback_preview(self, kinect_index):
        if self.state["preview"]["is_on"].get():
            # preview is already launched
            if self.state["preview"]["kinect_index"].get() == kinect_index:
                self.preview_frame.grid_remove()
                self.state["preview"]["is_on"].set(False)
                self.state["preview"]["kinect_index"].set(-1)
            else:
                # This should not be reachable
                pass
        else:
            # preview is not launched
            self.state["preview"]["is_on"].set(True)
            self.state["preview"]["kinect_index"].set(kinect_index)
            self.preview_frame.grid()
        self._update_preview_buttons_state()

    def _callback_about(self):
        self.menubar.focus_set()

        text = [
            "Developed by:",
            "Ilya Petrov and Vladimir Guzov",
            # "License, 2021"
        ]

        messagebox.showinfo("About Demo", '\n'.join(text))
    # ==================================================================================================================

    def _update_preview_buttons_state(self):
        is_on = self.state["preview"]["is_on"].get()

        for kinect_index, (state, button) in enumerate(zip(self._state_kinects, self._state_kinect_buttons)):
            kinect_id = state.kinect_id
            if is_on:
                if kinect_index ==  self.state["preview"]["kinect_index"].get():
                    button.configure(state=tk.NORMAL)
                    button.configure(text=f"Kinect id {kinect_id}\n(stop preview)", state=tk.NORMAL)
                else:
                    button.configure(state=tk.DISABLED)
            else:
                button.configure(text=f"Kinect id {kinect_id}\n(launch preview)", state=tk.NORMAL)

    def set_controller(self, controller):
        self._controller = controller
