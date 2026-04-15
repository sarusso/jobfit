from decimal import Decimal

# Credit rate — used only at top-up time (USD is not stored on TopUp).
USD_PER_CREDIT = Decimal('0.10')  # $5 -> 50 credits

TOP_UP_BUNDLES = [
    {'usd': Decimal('5'),  'credits': Decimal('50.00')},
    {'usd': Decimal('10'), 'credits': Decimal('110.00')},
    {'usd': Decimal('25'), 'credits': Decimal('300.00')},
]

# Action prices in credits.
ACTION_CV_SCORING = Decimal('2.00')
ACTION_JOB_IMPORT = Decimal('1.00')

# Description (stored in UsageLog.description) -> credits charged.
ACTION_PRICES = {
    'CV scoring': ACTION_CV_SCORING,
    'Job import': ACTION_JOB_IMPORT,
}


def credits_for_action(description: str) -> Decimal:
    return ACTION_PRICES.get(description, Decimal('0.00'))
