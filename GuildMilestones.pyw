# Double-click this file to open Guild Milestones (needs Python installed; no .exe required).
try:
    import milestone_gui
    milestone_gui.main()
except Exception:
    import traceback
    from tkinter import Tk, messagebox
    Tk().withdraw()
    messagebox.showerror("Guild Milestones", traceback.format_exc())
