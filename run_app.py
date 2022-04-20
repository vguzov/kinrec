from server.kinrec_server.app import KinRecApp

if __name__ == "__main__":
    # Create the class
    test_gui = KinRecApp(number_of_kinects=4)
    # run the event loop
    test_gui.mainloop()
