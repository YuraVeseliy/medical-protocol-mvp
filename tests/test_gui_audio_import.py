from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

from audio_mvp.gui import AudioApp
from audio_mvp.session import Session
from test_transcription import Recognizer


class AudioImportTests(unittest.TestCase):
    def test_audio_toolbar_opens_recorded_files(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        app = AudioApp(root, session=Session(Recognizer()))

        audio_controls = app.import_button.master.winfo_children()
        self.assertEqual(audio_controls, [app.import_button, app.process_button])
        self.assertTrue(app.process_button.instate(["disabled"]))

        sample = Path(__file__).with_name("fixtures") / "float32.wav"
        with patch("audio_mvp.gui.filedialog.askopenfilename", side_effect=[str(sample), ""]):
            app.import_button.invoke()
            self.assertEqual(app.audio_path, sample)
            self.assertTrue(app.process_button.instate(["!disabled"]))

            app.import_button.invoke()
            self.assertEqual(app.audio_path, sample)
            self.assertTrue(app.process_button.instate(["!disabled"]))
