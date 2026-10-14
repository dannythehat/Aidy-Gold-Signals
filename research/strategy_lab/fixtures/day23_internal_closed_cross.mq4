#property strict
bool LongEntry(double fast_prev, double slow_prev, double fast_now, double slow_now)
{
    return fast_prev <= slow_prev && fast_now > slow_now;
}
bool LongExit(double fast_prev, double slow_prev, double fast_now, double slow_now)
{
    return fast_prev >= slow_prev && fast_now < slow_now;
}
