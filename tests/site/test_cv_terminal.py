"""Checks for scripts/build-cv-terminal.py: run with `python3 -m unittest discover -s tests/site -p 'test_*.py'`."""
import importlib.util
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cvterm", ROOT / "scripts/build-cv-terminal.py")
cvterm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cvterm)
OUT = cvterm.build()
ANSI = re.compile(r"\033\[[0-9;]*m")


class TerminalCV(unittest.TestCase):
    def test_fits_80_columns(self):
        for name in ("cv.txt", "cv-plain.txt"):
            for i, line in enumerate(OUT[name].splitlines(), 1):
                self.assertLessEqual(len(ANSI.sub("", line)), 80, f"{name}:{i}")

    def test_plain_has_no_escape_codes_and_matches_coloured_text(self):
        self.assertNotIn("\033", OUT["cv-plain.txt"])
        self.assertEqual(ANSI.sub("", OUT["cv.txt"]), OUT["cv-plain.txt"])

    def test_every_cv_section_is_present(self):
        md = (ROOT / "services/public/site/cv.md").read_text()
        for section in re.findall(r"^## (.+)$", md, re.M):
            self.assertIn(f"== {section.upper()} ", OUT["cv-plain.txt"])

    def test_positioning_is_remote_only(self):
        for text in OUT.values():
            self.assertIsNone(re.search(r"(?i)ko[sš]ic|relocat|blue card", text))
        self.assertIn("Remote · any country", OUT["cv-plain.txt"])

    def test_json_resume_shape(self):
        d = json.loads(OUT["cv.json"])
        self.assertEqual(d["basics"]["name"], "Kalislav Smirnov")
        self.assertEqual(d["basics"]["location"]["countryCode"], "GE")
        self.assertEqual(len(d["work"]), 3)
        for w in d["work"]:
            self.assertRegex(w["startDate"], r"^\d{4}-\d{2}$")
            self.assertTrue(w["highlights"])
        self.assertTrue(d["skills"])

    def test_committed_files_are_fresh(self):
        for name, text in OUT.items():
            self.assertEqual((ROOT / "services/public/site" / name).read_text(), text, name)


if __name__ == "__main__":
    unittest.main()
