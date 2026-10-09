import unittest

from aiorganize.proposal import GroupingProposal, TabGroup


class ProposalTest(unittest.TestCase):
    def test_empty_and_duplicate_group_names_are_rejected(self):
        tabs = [{"id": "one"}, {"id": "two"}]
        for names in ([" ", "Other"], ["Learning", " learning "]):
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
