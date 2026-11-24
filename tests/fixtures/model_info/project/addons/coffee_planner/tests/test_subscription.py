from odoo.tests import tagged

from .common import PlannerCommon


class TestSubscription(PlannerCommon):
    def test_renew(self):
        pass

    def test_state(self):
        pass


@tagged('post_install', '-at_install')
class TestRenewWizard(PlannerCommon):
    def test_months(self):
        pass
