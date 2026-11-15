from django.contrib.auth.hashers import PBKDF2PasswordHasher


class DemoPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    """
    The public demo only (DEMO_MODE): its passwords are published on the sign-in page and its
    data is fictional and wiped nightly, so the hash cost protects nothing there, while at the
    free plan's 0.1 CPU the default 1.5M iterations make each sign-in (and each manager approval)
    take about 6 seconds. A real deployment keeps Django's default. See docs/adr/0008.
    """

    iterations = 100_000
