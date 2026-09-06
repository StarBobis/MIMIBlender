from datetime import datetime

from .log_utils import LOG

class TimerUtils:
    run_start = None
    run_end = None

    methodname_runstart_dict = {}

    @classmethod
    def Start(cls,func_name:str):
        # Clear run_start and run_end, and set run_start to the current time
        cls.run_start = datetime.now()
        cls.run_end = None
        cls.methodname_runstart_dict[func_name] = cls.run_start
        # LOG.newline()
        # print("[" + func_name + f"] started at: {cls.run_start} ")
        # LOG.newline()

    @classmethod
    def End(cls,func_name:str = ""):
        if cls.run_start is None:
            print("Timer has not been started. Call Start() first.")
            return
        
        # Set run_end to the current time
        cls.run_end = datetime.now()

        # LOG.newline()
        if func_name == "":
            # Calculate the time difference
            time_diff = cls.run_end - cls.run_start
            
            # Print the time difference
            print(f"last function time elapsed: {time_diff} ")
        else:
            time_diff = cls.run_end - cls.methodname_runstart_dict.get(func_name,0)

            # Print the time difference
            print("[" + func_name + f"] completed, total time elapsed: {time_diff} ")
        # LOG.newline()
        # Update run_start to the current time
        cls.run_start = cls.run_end
        # print(f"Timer updated start to: {cls.run_start}")
