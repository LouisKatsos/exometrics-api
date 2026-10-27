from app.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_allows_up_to_limit_then_blocks():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    assert all(limiter.hit('a', 5) is None for _ in range(5))
    assert limiter.hit('a', 5) is not None


def test_keys_are_independent():
    limiter = RateLimiter(clock=Clock())
    for _ in range(3):
        limiter.hit('a', 3)
    assert limiter.hit('a', 3) is not None
    assert limiter.hit('b', 3) is None


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(3):
        limiter.hit('a', 3)
    clock.now += 120  # two windows later: nothing counts any more
    assert limiter.hit('a', 3) is None


def test_zero_limit_disables():
    limiter = RateLimiter(clock=Clock())
    assert all(limiter.hit('a', 0) is None for _ in range(100))


def test_memory_is_bounded():
    clock = Clock()
    limiter = RateLimiter(max_keys=10, clock=clock)
    for i in range(100):
        limiter.hit(f'user-{i}', 5)
    assert len(limiter._state) <= 10
