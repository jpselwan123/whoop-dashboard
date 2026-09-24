"""The independent checker: a second implementation of every displayed number, run on every push.

Its value is that it is NOT the pipeline. So two things are enforced here: it imports nothing but the
standard library (never build_dashboard or any other module of this repo), and on the synthetic athlete
it agrees with the pipeline on every check.
"""
import ast, os, subprocess, sys, unittest

from helpers import make_data_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, 'tools', 'whoop_check.py')
OWN_MODULES = {'build_dashboard', 'ai_context', 'chat_server', 'env_config', 'whoop', 'helpers',
               'generate_demo_data', 'check_doc_stats', 'analyse_plan_effect', 'privacy_scan'}


class IndependenceTest(unittest.TestCase):
    def test_it_imports_nothing_from_this_repo(self):
        tree = ast.parse(open(CHECKER).read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertFalse(imported & OWN_MODULES, imported & OWN_MODULES)
        stdlib = getattr(sys, 'stdlib_module_names', None)          # 3.10+; CI's 3.12 checks it fully
        if stdlib:
            self.assertEqual(imported - set(stdlib), set())


class AgreementTest(unittest.TestCase):
    def test_it_agrees_with_the_pipeline_on_the_synthetic_athlete(self):
        d = make_data_dir(days=420)
        out = subprocess.run([sys.executable, CHECKER, d], capture_output=True, text=True, timeout=600)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:] + out.stderr[-2000:])
        self.assertRegex(out.stdout, r'^\d+ checks passed, 0 failed')


if __name__ == '__main__':
    unittest.main()
