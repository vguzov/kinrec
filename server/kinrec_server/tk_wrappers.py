import tkinter as tk
from tkinter import ttk


class FocusCheckButton(tk.Checkbutton):
    def __init__(self, *args, highlightthickness=0, **kwargs):
        tk.Checkbutton.__init__(self, *args, highlightthickness=highlightthickness, **kwargs)
        self.bind("<1>", lambda event: self.focus_set())


class FocusButton(ttk.Button):
    def __init__(self, *args, **kwargs):
        ttk.Button.__init__(self, *args, **kwargs)
        self.bind("<1>", lambda event: self.focus_set())


class FocusLabelFrame(tk.LabelFrame):
    def __init__(self, *args, highlightthickness=0, relief=tk.RIDGE, borderwidth=2, **kwargs):
        tk.LabelFrame.__init__(self, *args, highlightthickness=highlightthickness, relief=relief,
                               borderwidth=borderwidth, **kwargs)
        self.bind("<1>", lambda event: self.focus_set())

    def set_frame_state(self, state):
        def set_widget_state(widget, state):
            if widget.winfo_children is not None:
                for w in widget.winfo_children():
                    w.configure(state=state)

        set_widget_state(self, state)