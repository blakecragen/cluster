import os
import time

class TaskRunner:
    """
    Default strategy example.
    Simply copies input → output and adds a message.
    """

    def __init__(self):
        self.output_path = None

    def complete_task(self, input_filepath: str):
        """
        Perform the work.
        Should write the result into self.output_path.
        """
        # Create output filepath
        base = os.path.splitext(os.path.basename(input_filepath))[0]
        self.output_path = f"current_task_files/{base}_output.txt"

        # Example "task": append text to the file
        with open(input_filepath, "r") as f_in:
            data = f_in.read()

        with open(self.output_path, "w") as f_out:
            f_out.write("Processed by task_runner_default\n\n")
            f_out.write(data)
        
        time.sleep(10)

    def get_output_filepath(self):
        """
        Worker will upload this file.
        """
        return self.output_path
