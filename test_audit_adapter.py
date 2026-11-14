import unittest
from audit_adapter import convert

class AdapterTests(unittest.TestCase):
    def test_head_scope_unknown_and_dependency(self):
        data={'aoi_integration':{'captured_at':'t','records':[
            {'id':'A#1','repository':'A','number':1,'head_sha':'abc','main_sha':'m','files':None,'dependencies':[],'runs':[{'id':1,'head_sha':'old'},{'id':2,'head_sha':'abc'}]},
            {'id':'A#2','repository':'A','number':2,'files':['x'], 'dependencies':['A#1','A#9']}]}}
        g=convert(data)
        self.assertEqual(g['coverage']['file_lists_missing'],['A#1'])
        self.assertEqual(g['coverage']['unobserved_dependencies'],[{'dependent':'A#2','prerequisite':'A#9'}])
        self.assertEqual(g['coverage']['omitted_runs'][0]['run_id'],1)
        self.assertEqual([n['id'] for n in g['nodes'] if n['type']=='WorkflowRun'],['workflow_run:A:2'])
        self.assertEqual(next(n for n in g['nodes'] if n['id']=='pr:A#1')['main_sha'],'m')
        self.assertEqual(g['integration_batches'],[['A#1'],['A#2']])
    def test_invalid_identity(self):
        with self.assertRaises(ValueError): convert({'records':[{'id':'B#1','repository':'A','number':1}]})

if __name__=='__main__': unittest.main()
