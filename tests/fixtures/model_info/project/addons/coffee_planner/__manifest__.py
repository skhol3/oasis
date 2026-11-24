# Test-only synthetic module for module-info.
{
    'name': 'Coffee Planner',
    'summary': 'Plan coffee subscriptions',
    'version': '19.0.1.2.0',
    'depends': ['coffee', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/subscription_views.xml',
        './views/account_move_views.xml',
        'report/subscription_report.xml',
        'data/cron.xml',
        'views/missing.xml',
    ],
    'demo': ['demo/demo.xml'],
}
