import tkinter as tk

from .view import KinRecView


class KinRecApp(tk.Tk):
    def __init__(self, number_of_kinects):
        super().__init__()

        # Basic window properties
        # self.minsize(960, 480)
        # self.deiconify()
        self.title("Kinect Recorder server interface")
        # self.withdraw()
        # self.update_idletasks()
        # x = (self.winfo_screenwidth() - self.winfo_reqwidth()) / 2
        # y = (self.winfo_screenheight() - self.winfo_reqheight()) / 2
        # self.geometry("+%d+%d" % (x, y))

        # Add view
        self.view = KinRecView(parent=self, number_of_kinects=number_of_kinects)
        # self.view.grid(row=0, column=0, padx=10, pady=10)

        controller = None
        self.view.set_controller(controller)

    # def run(self):
    #     while True:
    #         ret_code, ret_msg = self.view.process_event()
    #         if ret_code == self.view.RET_CODE_ERROR:
    #             print(f"[EVENT LOOP] GUI error {ret_msg}")
    #         elif ret_code == self.view.RET_CODE_EXIT:
    #             print("[EVENT LOOP] Exiting GUI")
    #             break
    #         else:
    #             print("[EVENT LOOP]", ret_code, ret_msg)
