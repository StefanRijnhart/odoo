# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests.common import TransactionCase


class TestInheritRecordRules2manyUnlink(TransactionCase):

    def setUp(self):
        super(TestInheritRecordRules2manyUnlink, self).setUp()
        self.demo = self.env.ref('base.user_demo')
        self.demo.write(
            {'groups_id': [(4, self.env.ref('base.group_system').id)]})
        self.company1 = self.demo.company_id
        self.company2 = self.company1.create({'name': __name__})
        self.user1 = self.env['res.users'].create({
            'name': '%suser1' % __name__,
            'login': '%suser1' % __name__[-20],
            'email': '%s1@example.com' % __name__,
            'company_ids': [(4, self.company1.id)],
            'company_id': self.company1.id,
        })
        self.user2 = self.env['res.users'].create({
            'name': '%suser2' % __name__,
            'login': '%suser2' % __name__[-20],
            'email': '%s2@example.com' % __name__,
            'company_ids': [(4, self.company2.id)],
            'company_id': self.company2.id,
        })
        self.user3 = self.env['res.users'].create({
            'name': '%suser3' % __name__,
            'login': '%suser3' % __name__[-20],
            'email': '%s3@example.com' % __name__,
            'company_ids': [(4, self.company1.id)],
            'company_id': self.company1.id,
        })
        self.group = self.env['res.groups'].create({
            'name': __name__,
            'users': [(4, self.user1.id), (4, self.user2.id)],
        })
        # Disable the company record rule on res.users and introduce one on
        # res.partner
        self.env['ir.rule'].search(
            [('model_id.model', '=', 'res.users')]).write({'active': False})
        self.env['ir.rule'].create({
            'domain_force': (
                "['|', ('company_id','child_of',[user.company_id.id]),"
                "('company_id','=',False)]"),
            'model_id': self.env.ref('base.model_res_partner').id})

    def test_01_write_inherit_record_rules_2many_unlink(self):
        """ record rules from inherited models are applied when unlinking 2many values """
        self.assertIn(self.user1, self.group.users)
        self.assertIn(self.user2, self.group.users)

        # The user does not have access to user2
        self.assertNotIn(self.user2.partner_id, self.env(
            user=self.demo)['res.partner'].search([]))
        group = self.group.sudo(user=self.demo)

        # Therefore, user2 is not accessible as a group member
        self.assertNotIn(self.user2, group.users)
        ids = (group.users + self.user3).ids

        group.write({'users': [(6, 0, ids)]})

        # After the user updates the group member list,
        # The inaccessible user2 is still a member of the group
        self.assertIn(self.user1, self.group.users)
        self.assertIn(self.user2, self.group.users)
        self.assertIn(self.user3, self.group.users)
