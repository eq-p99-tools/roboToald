def dkp_from_duration(rate: int, duration_seconds: float) -> int:
    """Calculate DKP earned from an RTE session.

    Port of Ruby TrackingDkpCalculator.dkp_from_duration.
    Full rate per complete hour, prorated for partial hours.
    """
    total_seconds = max(0, duration_seconds)
    total_hours = total_seconds / 3600.0
    full_hours = int(total_hours)
    remaining_minutes = (total_seconds - full_hours * 3600) / 60.0
    subrate = round((remaining_minutes / 60.0) * rate)
    return (rate * full_hours) + subrate
