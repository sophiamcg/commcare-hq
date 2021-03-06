from __future__ import absolute_import
from django.test import SimpleTestCase
from corehq.apps.performance_sms.exceptions import InvalidParameterException
from corehq.apps.performance_sms.models import PerformanceConfiguration, TemplateVariable
from corehq.apps.performance_sms.parser import extract_params, parse_param, VALID_NAMESPACES, GLOBAL_NAMESPACE, \
    get_parsed_params


class ParserTest(SimpleTestCase):

    def test_extraction(self):
        params = extract_params('Hello {user.username} - you have completed {template_var} forms today!')
        self.assertEqual(2, len(params))
        self.assertEqual('user.username', params[0])
        self.assertEqual('template_var', params[1])

    def test_get_params(self):
        params = get_parsed_params('Hello {user.username} - you have completed {template_var} forms today!')
        self.assertEqual(2, len(params))
        self.assertEqual('user', params[0].namespace)
        self.assertEqual('username', params[0].variable)
        self.assertEqual(GLOBAL_NAMESPACE, params[1].namespace)
        self.assertEqual('template_var', params[1].variable)

    def test_validate_bad_formats(self):
        invalid_test_cases = [
            None,
            '',
            'too.many.periods',
            'bad.namespace',
            ' prewhitespace',
            'postwhitespace ',
            'inner whitespace',
        ]
        for invalid in invalid_test_cases:
            with self.assertRaises(InvalidParameterException):
                parse_param(invalid)
            if invalid:
                with self.assertRaises(InvalidParameterException):
                    template = 'Hello {%s}' % invalid
                    PerformanceConfiguration(template=template).validate()

    def test_valid_namespaces(self):
        for namespace in VALID_NAMESPACES:
            unparsed = '{}.variable_name'.format(namespace)
            parsed = parse_param(unparsed)
            self.assertEqual(namespace, parsed.namespace)
            self.assertEqual('variable_name', parsed.variable)

    def test_default_namespace(self):
        parsed = parse_param('variable_name')
        self.assertEqual(GLOBAL_NAMESPACE, parsed.namespace)
        self.assertEqual('variable_name', parsed.variable)

    def test_global_vars_validation(self):
        template = 'Hello {name} - you have completed {count} forms today!'
        # if 0 or 1 are defined it should fail
        with self.assertRaises(InvalidParameterException):
            PerformanceConfiguration(template=template).validate()
        with self.assertRaises(InvalidParameterException):
            PerformanceConfiguration(template=template, template_variables=[
                TemplateVariable(slug='name', type='form'),
            ]).validate()
        # if both are defined it should not succeed
        PerformanceConfiguration(template=template, template_variables=[
            TemplateVariable(slug='name', type='form'),
            TemplateVariable(slug='count', type='form'),
        ]).validate()
