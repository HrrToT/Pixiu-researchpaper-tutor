"""A module-count match cannot hide deletion of older parameterized tests."""
import importlib.util
from pathlib import Path


def runner():
    path=Path(__file__).resolve().parents[2]/'scripts/verify-deep-research-offline.py'
    spec=importlib.util.spec_from_file_location('research_regression_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def write(path,cases):
    import xml.etree.ElementTree as ET
    root=ET.Element('testsuite')
    for cls,name in cases:ET.SubElement(root,'testcase',classname=cls,name=name)
    ET.ElementTree(root).write(path,encoding='utf8')


def test_same_module_and_same_count_cannot_hide_replaced_old_tests(tmp_path):
    old=tmp_path/'old.xml';new=tmp_path/'new.xml'
    write(old,[('tests.test_deep_research_example','test_old[a]'),('tests.test_deep_research_example','test_old[b]')])
    write(new,[('tests.test_deep_research_example','test_new[a]'),('tests.test_deep_research_example','test_new[b]')])
    r=runner();assert r.junit_modules(old)==r.junit_modules(new)
    assert len(r.junit_case_ids(old))==len(r.junit_case_ids(new))
    assert r.junit_case_ids(old)-r.junit_case_ids(new)=={
        'test_deep_research_example::test_old[a]','test_deep_research_example::test_old[b]'}


def test_namespaced_classes_and_literal_parameter_separators_remain_distinct(tmp_path):
    path=tmp_path/'cases.xml'
    write(path,[('tests.test_deep_research_example.TestScope','test_f[a::b]'),
                ('tests.test_deep_research_example.TestScope','test_f[a/b]'),
                ('tests.unrelated','test_other')])
    assert runner().junit_case_ids(path)=={
        'test_deep_research_example.TestScope::test_f[a::b]',
        'test_deep_research_example.TestScope::test_f[a/b]'}


def test_adding_new_cases_preserves_every_old_case(tmp_path):
    old=tmp_path/'old.xml';new=tmp_path/'new.xml';case=('test_deep_research_example','test_old')
    write(old,[case]);write(new,[case,('tests.test_deep_research_new','test_new')])
    r=runner();assert not r.junit_case_ids(old)-r.junit_case_ids(new)
