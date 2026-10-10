import unittest
from contextlib import redirect_stdout
from io import StringIO

from aiorganize.proposal import GroupingProposal, TabGroup, print_preview
from pydantic import ValidationError


class ProposalTest(unittest.TestCase):
    def test_other_group_appears_last_in_preview(self):
        proposal = GroupingProposal(
            groups=[
                TabGroup(name="Other", tab_ids=["one"]),
                TabGroup(name="Dev", tab_ids=["two"]),
            ]
        )
        output = StringIO()
        with redirect_stdout(output):
            print_preview(
                proposal,
                [
                    {"id": "one", "title": "Blank", "url": "about:blank"},
                    {"id": "two", "title": "Python", "url": "https://example.test"},
                ],
            )
        self.assertLess(output.getvalue().index("\nDev\n"), output.getvalue().index("\nOther\n"))

    def test_group_name_is_short_enough_for_chrome(self):
        with self.assertRaises(ValidationError):
            TabGroup(name="Development", tab_ids=["one"])
        self.assertEqual(TabGroup(name="Dev", tab_ids=["one"]).name, "Dev")

    def test_empty_and_duplicate_group_names_are_rejected(self):
        tabs = [{"id": "one"}, {"id": "two"}]
        for names in ([" ", "Other"], ["Dev", " dev "]):
            with self.subTest(names=names):
                proposal = GroupingProposal(
                    groups=[
                        TabGroup(name=names[0], tab_ids=["one"]),
                        TabGroup(name=names[1], tab_ids=["two"]),
                    ]
                )
                with self.assertRaisesRegex(ValueError, "nonempty and unique"):
                    proposal.validate_tabs(tabs)

    def test_invalid_membership_is_rejected(self):
        tabs = [{"id": "one"}, {"id": "two"}]
        for ids in (["one"], ["one", "invented"], ["one", "one", "two"]):
            with self.subTest(ids=ids):
                proposal = GroupingProposal(groups=[TabGroup(name="Example", tab_ids=ids)])
                with self.assertRaises(ValueError):
                    proposal.validate_tabs(tabs)


if __name__ == "__main__":
    unittest.main()
