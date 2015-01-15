# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2013 OpenERP SA (<http://openerp.com>).
#
#    @authors: Stefan Rijnhart (Therp B.V.)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.tools.translate import _


class purchase_requisition_merge(orm.TransientModel):
    _name = 'purchase.requisition.merge'
    _description = 'Purchase Requisistion Merge'

    _columns = {
        'line_ids': fields.many2many(
            'purchase.requisition.line',
            'requisition_merge_requisition_line',
            'requisition_merge_id', 'requisition_line_id',
            'Requisition lines',
            domain = [('requisition_id.state', '=', 'draft'),
                      ('requisition_id.purchase_ids', '=', False)]),
        }

    def check_requisitions(self, cr, uid, requisitions, context=None):
        """
        Check if requisitions from which the lines to merge come from
        the same company and warehouse.
        """
        for requisition in requisitions[1:]:
            if requisition.warehouse_id != requisitions[0].warehouse_id:
                orm.except_orm(
                    _('Error'),
                    _('Requisitions to merge need to have the same '
                      'warehouse setting'))
            if requisition.company_id != requisitions[0].company_id:
                orm.except_orm(
                    _('Error'),
                    _('Requisitions to merge need to have the same company'))
        return True

    def merge_requisition_lines(self, cr, uid, merge_ids, context=None):
        """
        Merge the given requisition lines into a new requisition, and clean
        up any dangling requisitions with no lines.

        @return: act window to the form view of the newly created requisition
        """
        merge = self.browse(cr, uid, merge_ids[0], context=context)
        if not merge.line_ids:
            orm.except_orm(
                _('Error'),
                _('Please select a number of requisition lines to merge.'))
            
        # Get a unique set of requisitions from the list of lines
        requisitions = list(set(
                [line.requisition_id for line in merge.line_ids]))
        self.check_requisitions(cr, uid, requisitions, context=context)
        requisition_obj = self.pool['purchase.requisition']
        procurement_obj = self.pool['procurement.order']
        target_requisition_id = requisition_obj.create(
            cr, uid, {
            'warehouse_id': requisitions[0].warehouse_id.id or False,
            'company_id': requisitions[0].company_id.id,
            }, context=context)

        minimum_date_planned = merge.line_ids[0].date_planned
        for line in merge.line_ids:
            if line.date_planned < minimum_date_planned:
                minimum_date_planned = line.date_planned

            # Update procurement subflows
            procurement_ids = procurement_obj.search(
                cr, uid, [('requisition_line_id', '=', line.id)],
                context=context)
            cr.execute(
                """
                UPDATE wkf_workitem
                SET subflow_id = new_requisition_instance.id
                FROM wkf_instance procurement_instance,
                    wkf_instance old_requisition_instance,
                    wkf_instance new_requisition_instance
                WHERE wkf_workitem.subflow_id = old_requisition_instance.id
                    AND old_requisition_instance.res_type = 'purchase.requisition'
                    AND old_requisition_instance.res_id = %s
                    AND new_requisition_instance.res_type = 'purchase.requisition'
                    AND new_requisition_instance.res_id = %s
                    AND wkf_workitem.inst_id = procurement_instance.id
                    AND procurement_instance.res_type = 'procurement.order'
                    AND procurement_instance.res_id in %s
                """, (
                    line.requisition_id.id,
                    target_requisition_id,
                    tuple(procurement_ids)))

            line.write({'requisition_id': target_requisition_id})

        requisition_obj.write(
            cr, uid, target_requisition_id,
            {'date_end': minimum_date_planned}, context=context)
            
        requisitions[0].refresh()
        requisition_obj.unlink(
            cr, uid,
            [req.id for req in requisitions if not req.line_ids],
            context=context)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Requisition'),
            'res_model': 'purchase.requisition',
            'res_id': target_requisition_id,
            'view_type': 'form',
            'view_mode': 'form,tree',
            'target': 'current',
            'nodestroy': True,
        }
