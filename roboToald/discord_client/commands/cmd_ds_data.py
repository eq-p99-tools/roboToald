import calendar
import datetime

import disnake

from roboToald.discord_client.commands import cmd_ds
from roboToald.db.models import points as points_model
from roboToald import utils


@cmd_ds.ds.sub_command_group()
async def data(inter: disnake.ApplicationCommandInteraction):
    pass


@data.sub_command(
    name="calendar",
    description="Render a calendar of urn purchases.")
async def calendar_cmd(
        inter: disnake.ApplicationCommandInteraction):
    # Defer the response to avoid timeouts
    await inter.response.defer()

    # Get all urn purchases
    urns = points_model.get_points_spent(inter.guild_id)
    if not urns:
        await inter.send(content="No urn purchases found.")
        return

    # Create a calendar of urn purchases
    cal_dict = {}
    for urn in urns:
        date = urn.time.date()
        if date not in cal_dict:
            cal_dict[date] = []
        cal_dict[date].append(urn)

    cal_message = "**Urn Purchase Calendar**"

    # Get the year and month of the first urn purchase
    first_date = min(cal_dict.keys())
    first_year = first_date.year
    first_month = first_date.month
    today = datetime.date.today()
    months = []
    for year in range(first_year, datetime.date.today().year + 1):
        for month in range(1, 13):
            if year == first_year and month < first_month:
                continue
            if year >= today.year and month > today.month:
                break
            cal_month = calendar.month(year, month, w=5)
            cal_month = pad_month(cal_month)
            for date in cal_dict:
                if date.year == year and date.month == month:
                    cal_month = mark_date(cal_month, date.day)
            months.append(cal_month)

    month_groups = combine_months(months, 2)
    await inter.send(content=cal_message)
    cal_message = ""
    for i, month_group in enumerate(month_groups):
        if i % 2 == 0 and i != 0:
            await inter.send(content=f'```{cal_message}```')
            cal_message = ""
        horizontal_line = ""
        if i % 2 != 0:
            horizontal_line = "\n\n" + "=" * len(month_group.splitlines()[0]) + "\n\n"
        cal_message += f"{horizontal_line}" + month_group
    if cal_message:
        await inter.send(content=f'```{cal_message}```')


def combine_months(months, num_cols):
    # Group months into sets of `num_cols`
    month_groups = []
    one_set = []
    for i, month in enumerate(months):
        if i % num_cols == 0 and i != 0:
            month_groups.append(one_set)
            one_set = []
        one_set.append(month)
    month_groups.append(one_set)

    # Combine the months in each set, line by line
    combined_months = []
    for month_set in month_groups:
        one_set = []
        # Find the number of lines in the longest month
        max_lines = max(len(month.splitlines()) for month in month_set)
        for i in range(max_lines):
            line = ""
            for month in month_set:
                try:
                    line += month.splitlines()[i] + " || "
                except IndexError as e:
                    line += " " * len(month.splitlines()[0]) + " || "
            one_set.append(line[:-4])
        combined_months.append('\n'.join(one_set))
    return combined_months


def pad_month(cal_month):
    cal_month = cal_month.splitlines()
    max_width = max(len(line) for line in cal_month)
    for i, line in enumerate(cal_month):
        if len(line) < max_width:
            cal_month[i] = line + " " * (max_width - len(line))
    return "\n".join(cal_month)


def mark_date(cal_month, day):
    cal_month = cal_month.splitlines()
    for i, line in enumerate(cal_month):
        if str(day) in line:
            cal_month[i] = line.replace(f" {day} ", f"[{day}]")
    return "\n".join(cal_month)


@data.sub_command(description="Show urn purchase history.")
async def purchases(
        inter: disnake.ApplicationCommandInteraction):
    # Defer the response to avoid timeouts
    await inter.response.defer()

    # Get all urn purchases
    urns = points_model.get_points_spent(inter.guild_id)
    if not urns:
        await inter.send(content="No urn purchases found.")
        return

    # Create a list of urn purchases
    urn_message = "**Urn Purchase History**\n"
    for urn in urns:
        urn_message += f"* <@{urn.user_id}>: {urn.points} points at <t:{int(urn.time.timestamp())}>.\n"

    # Send the list of urn purchases
    await utils.send_and_split(inter, urn_message)


@data.sub_command(description="Show a historical overview of the DS camp.")
async def overview(
        inter: disnake.ApplicationCommandInteraction):
    # Defer the response to avoid timeouts
    await inter.response.defer()

    # Get total number of points earned
    earned_by_member = {}
    all_earned = points_model.get_points_earned(inter.guild_id)
    total_earned = 0
    for point_event in all_earned:
        # Add member points earned
        if point_event.user_id not in earned_by_member:
            earned_by_member[point_event.user_id] = 0
        earned_by_member[point_event.user_id] += point_event.points

        # Add total points
        total_earned += point_event.points
    num_players = len(earned_by_member)

    # Get total number of minutes spent
    minutes_by_member = {}
    total_minutes = 0
    all_audits = points_model.get_events_since_time(
        inter.guild_id, datetime.datetime.fromtimestamp(0))
    all_audits_by_member = points_model.get_event_pairs_split_members(all_audits)
    for member, member_audits in all_audits_by_member.items():
        minutes = 0
        for start_time, stop_time in member_audits.items():
            minutes += (stop_time - start_time).total_seconds() / 60
        minutes_by_member[member] = minutes
        total_minutes += minutes

    # Get total amount of points spent and related statistics
    spent_by_member = {}
    num_spent_by_member = {}
    all_spent = points_model.get_points_spent(inter.guild_id)
    num_urns = len(all_spent)
    total_spent = 0
    max_spent = 0
    max_spent_by = "nobody"
    min_spent = None
    min_spent_by = "nobody"
    for spent_event in all_spent:
        total_spent += spent_event.points
        # Add member points spent
        if spent_event.user_id not in spent_by_member:
            spent_by_member[spent_event.user_id] = 0
        spent_by_member[spent_event.user_id] += spent_event.points
        # Add member urn count
        if spent_event.user_id not in num_spent_by_member:
            num_spent_by_member[spent_event.user_id] = 0
        num_spent_by_member[spent_event.user_id] += 1
        # Check for max/min spent
        if spent_event.points > max_spent:
            max_spent = spent_event.points
            max_spent_by = spent_event.user_id
        if min_spent is None or spent_event.points < min_spent:
            min_spent = spent_event.points
            min_spent_by = spent_event.user_id

    # Average urns per week since first urn and other statistics
    first_urn = all_spent[0].time
    first_urn_buyer = all_spent[0].user_id
    time_since_first = datetime.datetime.now() - first_urn
    weeks_since_first = time_since_first.days / 7
    urns_per_week = num_urns / weeks_since_first
    urns_per_week_rounded = round(num_urns / weeks_since_first, 1)
    urns_per_week_adjective = "almost" if urns_per_week_rounded > urns_per_week else "over"
    average_cost = round(total_spent / num_urns, 2)

    message_camp = (
        "**Camp Statistics**\n"
        f"Together, `{num_players}` players spent `{round(total_minutes)}` "
        f"minutes in camp, earning `{total_earned}` points. "
        f"Players spent `{total_spent}` of those points to buy `{num_urns}` urns "
        f"at an average cost of `{average_cost} points` each. "
        f"That's {urns_per_week_adjective} `{urns_per_week_rounded}` urns per week!\n"
        "\n"
        "**Hall of Fame**\n"
        f"The first urn was purchased <t:{int(first_urn.timestamp())}:R>"
        f" on <t:{int(first_urn.timestamp())}:D> by <@{first_urn_buyer}>.\n"
        f"The cheapest urn was purchased by <@{min_spent_by}> for `{min_spent} points`.\n"
        f"The most expensive urn was purchased by <@{max_spent_by}> for `{max_spent} points`.\n"
    )
    message_members = "**Member Statistics**\n"
    for member, points_earned in earned_by_member.items():
        points_spent = spent_by_member.get(member, 0)
        num_urns = num_spent_by_member.get(member, 0)
        member_minutes = round(minutes_by_member.get(member, 0))
        average_string = ""
        if num_urns > 0:
            average_cost = round(points_spent / num_urns, 2)
            average_string = f" (avg. `{average_cost} points` per urn)"
        message_members += (
            f"* <@{member}> earned `{points_earned} points` over "
            f"`{member_minutes} minutes`, and spent a total of "
            f"`{points_spent} points` on `{num_urns} urn{'s' if num_urns != 1 else ''}`"
            f"{average_string}.\n")

    await inter.send(
        content=message_camp, allowed_mentions=disnake.AllowedMentions(users=False)
    )

    await utils.send_and_split(inter, message_members)
