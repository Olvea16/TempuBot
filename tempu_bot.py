import discord
import asyncio
import datetime
import time
import json
import matplotlib.pyplot as plt
import numpy as np
import re

from discord.ext.tasks import loop
from discord.ext.commands import Bot, has_permissions, has_any_role

import ranking_html_factory
from wrapper_warcraftlogs import getReportsGuild, getReportFightCode, getParses
import raiders
from defs import dir_path, colors, getParseColor, timestamp
import defs
past_file_path = dir_path + r'/past_raid.json'
import attendance
import google_sheets_test

from selenium import webdriver
from selenium.webdriver.common.keys import Keys  
from selenium.webdriver.chrome.options import Options 
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# DEFINITIONS
debug = []

with open(dir_path + '/discord_token.txt') as f:
    discord_token = f.readline()

# SETUP
client = Bot('!')

# FUNCTIONS
try:
    dates = json.load(open(dir_path + '/dates.json', encoding=defs.encoding))
except FileNotFoundError:
    dates = []

print(timestamp(), 'dir_path: ' + dir_path)

def addDate(channelid, dayStart, dayEnd, timeStart, timeEnd):
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    dayStart = days.index(dayStart) + 1
    dayEnd = days.index(dayEnd) + 1
    if (dayEnd < dayStart): dayEnd += 7

    hourStart, minuteStart = map(int, timeStart.split('.'))
    hourEnd, minuteEnd = map(int, timeEnd.split('.'))

    startDate = datetime.datetime(year=1, month=1, day=dayStart, hour=hourStart, minute=minuteStart)
    endDate = datetime.datetime(year=1, month=1, day=dayEnd, hour=hourEnd, minute=minuteEnd)

    entry = {'id': channelid, 'start': startDate.strftime('%d-%H:%M:%S'), 'end': endDate.strftime('%d-%H:%M:%S')}
    if 'addDate' in debug: print (timestamp(), 'adddate', entry)
    dates.append(entry)
    json.dump(dates, open(dir_path + '/dates.json', 'w', encoding=defs.encoding))

def isNow(dateStart, dateEnd):
    now = datetime.datetime.now()
    dayNow = now.weekday() + 1
    hourNow = now.hour
    minuteNow = now.minute
    dateNow = datetime.datetime(year=1, month=1, day=dayNow, hour=hourNow, minute=minuteNow).strftime('%d-%H:%M:%S')
    if 'isNow' in debug: print(timestamp(), 'isNow', dateStart, dateNow, dateEnd)
    return (dateStart <= dateNow <= dateEnd)

def getDateFromtimestamp(timestamp):
    date = datetime.datetime.utcfromtimestamp(timestamp/1000)
    dateString = date.strftime('%d/%m/%Y')
    return dateString

bossEncounterIDs = {
    663: 'Lucifron', 
    664: 'Magmadar', 
    665: 'Gehennas', 
    666: 'Garr', 
    667: 'Baron Geddon', 
    668: 'Shazzrah', 
    669: 'Sulfuron Harbinger', 
    670: 'Golemagg the Incinerator',
    671: 'Majordomo Executus', 
    672: 'Ragnaros', 
    1084: 'Onyxia'}

def get_new_parses(metrics):
    past_start = ""
    past_bosses = []

    try:
        with open(past_file_path, encoding=defs.encoding) as file:
            past = json.load(file)
            past_start = past['start']
            past_bosses = past['bosses']
    except FileNotFoundError:
        past = {}

    new_parses = []
    report_info = getReportsGuild('Hive Mind')[0]
    if (report_info['start'] != past_start): 
        past_bosses = []

    report = getReportFightCode(report_info['id'])

    fights = []
    for fight in report['fights']:
        if fight['boss'] is not 0 and fight['kill'] and fight['name'] not in past_bosses:
            fights.append(fight)

    for fight in fights:
        summary = {'fight': fight, 'parses': {}, 'report': {'title': report_info['title'], 'id': report_info['id']}}
        for metric in metrics:
            url_dps = 'https://classic.warcraftlogs.com/reports/' + report_info['id'] + '#fight=' + str(fight['id']) + '&view=rankings&playermetric=' + metric

            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument("keep_alive=True")
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

            print(timestamp(), '*' + url_dps)
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(url_dps)

            element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "primary")))
            fight['deaths'] = element.text

            element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "player-table")))
            row_elements = element.find_elements_by_tag_name('tr')[1:]

            for row_element in row_elements:
                row_stats = {}
                cell_elements = row_element.find_elements_by_tag_name('td')
                
                name = cell_elements[4].find_element_by_tag_name('a').get_attribute('innerHTML').lower()
                role = raiders.getRaiderAttribute(name, 'role')

                if ((metric == 'dps' and role in ['melee', 'ranged']) or (metric == 'hps' and role == 'healer')):
                    row_stats['percentile'] = int(cell_elements[0].text)
                    row_stats['rank'] = cell_elements[1].text
                    row_stats['out_of'] = int(cell_elements[2].text.replace(',', ''))
                    row_stats['best_rank'] = cell_elements[3].text
                    row_stats['dps'] = float(cell_elements[5].text)
                    row_stats['ilvl'] = int(cell_elements[6].text)
                    row_stats['ipercentile'] = int(cell_elements[7].text)

                    summary['parses'][name] = row_stats
        new_parses.append(summary)
        past_bosses.append(fight['name'])
        past = {'start': report_info['start'], 'bosses': past_bosses}
        json.dump(past, open(past_file_path, 'w', encoding=defs.encoding), ensure_ascii=False, indent=4)
    return new_parses

# LOOPS
@loop(hours=1)
async def update_raiders_task():
    print(timestamp(), 'update_raiders_task started')
    google_sheets_test.update_raiders()
    print(timestamp(), 'update_raiders_task finished')

@loop(seconds=20)
async def wclRaidTask():
    for entry in dates:
        if 'wclRaidTask' in debug: print(timestamp(), 'wclRaidTask', entry['id'], entry['start'], entry['end'], isNow(entry['start'], entry['end']))

        if (isNow(entry['start'], entry['end'])):
            fights = get_new_parses(['dps', 'hps'])
            for f in fights:
                fight = f['fight']
                parses = f['parses']
                report = f['report']

                melee_parses = []
                ranged_parses = []
                healer_parses = []

                for name in parses:
                    if (raiders.getRaiderAttribute(name, 'role') == 'ranged'): ranged_parses.append(name)
                    elif (raiders.getRaiderAttribute(name, 'role') == 'melee'): melee_parses.append(name)
                    elif (raiders.getRaiderAttribute(name, 'role') == 'healer'): healer_parses.append(name)

                group_names = ['Melee', 'Ranged', 'Healers']
                metric = ['DPS', 'DPS', 'HPS']

                tables = ""
                for i, current_parses in enumerate([melee_parses, ranged_parses, healer_parses]):
                    rows = ""
                    for j, name in enumerate(current_parses[:3]):
                        parse = parses[name]
                        percentile = parse['percentile']
                        class_color = colors[raiders.getRaiderAttribute(name, 'class')]
                        rows += ranking_html_factory.get_row(
                            number=str(j + 1), 
                            name=name,
                            name_color=class_color,
                            parse=str(percentile), 
                            parse_color=getParseColor(percentile), 
                            rank=parse['rank'],
                            dps=str(parse['dps']), 
                        )
                    
                    avg_parse = 0
                    avg_rank = 0
                    avg_dps = 0

                    n = len(current_parses)

                    for name in current_parses:
                        avg_parse += parses[name]['percentile'] / n
                        avg_rank += int(parses[name]['rank'].replace('~','')) / n
                        avg_dps += parses[name]['dps'] / n
                        
                    avg_parse = round(avg_parse, 1)
                    avg_rank = int(avg_rank)
                    avg_dps = round(avg_dps, 1)

                    tables += ranking_html_factory.get_table(
                        group_name=group_names[i], 
                        metric=metric[i],
                        rows=rows, 
                        avg_parse=str(avg_parse), 
                        avg_parse_color=getParseColor(avg_parse),
                        avg_rank=str(avg_rank),
                        avg_dps=str(avg_dps)
                    )

                html = ranking_html_factory.get_html(fight['name'], tables)
                link = 'https://classic.warcraftlogs.com/reports/' + str(report['id']) + '#fight=' + str(fight['id'])

                html_path = dir_path + '/boss_summaries/' + fight['name'] + '.html'
                image_path = dir_path + '/boss_summaries/' + fight['name'] + '.png'
                with open(html_path, 'w') as file:
                    file.write(html)

                chrome_options = Options()
                chrome_options.add_argument('--headless')
                chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

                driver = webdriver.Chrome(options=chrome_options)
                driver.get('file:///' + html_path)

                body = driver.find_element_by_tag_name('body')
                size = body.size
                driver.set_window_size(size['width'], size['height'])

                driver.save_screenshot(image_path)

                pre_message = "__**" + fight['name'] + "**__" + '\n'
                pre_message += 'Participants: ' + str(len(parses)) + '\n'
                pre_message += 'Time: ' + str(round((fight['end_time'] - fight['start_time'])/1000, 1)) + 's' + '\n'
                pre_message += 'Deaths: ' + fight['deaths'] + '\n'
                post_message = "Log link: " + link 

                channel = client.get_channel(entry['id'])

                await channel.send(content=pre_message, file=discord.File(image_path))
                await channel.send(content=post_message)

# COMMANDS
@client.command(name = 'echo')
@has_any_role('Officer', 'Admin')
async def echo(ctx, *args):
    print(timestamp(), 'echo', args)
    await ctx.message.delete()
    if (len(args) > 0): 
        with open(dir_path + '/echo.log', 'w+', encoding=defs.encoding) as file:
            file.write(' '.join(args) + '\n')
        await ctx.send(content=' '.join(args))
    else: await ctx.send(content='echo')

@client.command(name = 'forget', help='Removes a specific boss from the list of cleared bosses this week. Example: \'!forget Rag\'')
@has_any_role('Officer', 'Admin')
async def forget_boss(ctx, *args):
    print(timestamp(), 'forget', args)
    await ctx.message.delete()
    if len(args) == 0:
        await ctx.send(content='Incorrect number of arguments. Use \'!help {}\' for help on how to use this feature.'.format(ctx.command.name))
    else:
        boss_name = ' '.join(args)
        bosses = [bossEncounterIDs[key] for key in bossEncounterIDs]

        match = ''
        for boss in bosses:
            if boss_name.lower() in boss.lower():
                match = boss

        if match == '':
            await ctx.send(content='Input \'' + boss_name + '\' not understood. Use \'!help {}\' for help on how to use this feature.'.format(ctx.command.name))
        else:
            try:
                past = json.load(open(past_file_path, encoding=defs.encoding))
                if match in past['bosses']:
                    past['bosses'].remove(match)
                json.dump(past, open(past_file_path, 'w', encoding=defs.encoding), ensure_ascii=False, indent=4)
                await ctx.send(content='Deleted boss ' + match + ' from bot memory.')
            except FileNotFoundError:
                pass


@client.command(name = 'addraid', help = 'Adds raid to the schedule. Example: \'!addraid sunday 19.30 sunday 22.00\'')
@has_any_role('Officer', 'Admin')
async def wcl_addraid(ctx, *args):
    print(timestamp(), 'addraid', len(args), args)
    await ctx.message.delete()

    if len(args) == 4:
        id = ctx.message.channel.id
        addDate(id, args[0], args[2], args[1], args[3])
    else:
        await ctx.send(content='Incorrect number of arguments. Use \'!help {}\' for help on how to use this feature.'.format(ctx.command.name))

@client.command(name = 'removeraid', help="Removes a raid from the schedule. You select raid by index in \'!listraids\'. Example: \'!removeraid 1\'")
@has_any_role('Officer', 'Admin')
async def wcl_remove_raid(ctx, *args):
    print(timestamp(), 'addraid', len(args), args)
    await ctx.message.delete()

    if len(args) == 1:
        i = int(args[0])
        del dates[i]
    else:
        await ctx.send(content='Incorrect number of arguments. Use \'!help {}\' for help on how to use this feature.'.format(ctx.command.name))

@client.command(name = 'listraids', help='Lists the raids on the schedule. Example: \'!listraids\'')
@has_any_role('Officer', 'Admin')
async def wcl_list_raids(ctx, *args):
    print(timestamp(), 'addraid', len(args), args)
    await ctx.message.delete()

    if len(args) == 0:
        message = "**Raid Times:**\n"
        for i, entry in enumerate(dates):
            message += '{} - id: {}, start: {}, end: {}\n'.format(i, entry['id'], entry['start'], entry['end'])
        await ctx.send(content=message)
    else:
        await ctx.send(content='Incorrect number of arguments. Use \'!help {}\' for help on how to use this feature.'.format(ctx.command.name))

@client.command(name = 'attendance', help = 'Creates a graph displaying raid attendance. Optionally includes amount of months to go back. Example: \'!attendance 3\'')
@has_any_role('Officer', 'Admin')
async def wcl_attendance(ctx, *args):
    print(timestamp(), 'attendance', args)
    await ctx.message.delete()
    days = None
    months = None
    # Argument handling

    if (len(args) > 0 and args[0] == 'inspect'):
        verbose = False
        if ('-v' in args):
            verbose = True
            args = list(args)
            del args[args.index('-v')]
            
        brief = False
        if ('-b' in args):
            brief = True
            args = list(args)
            del args[args.index('-b')]

        names = []
        message = "Attendance summary:\n"

        i = 1
        while (i < len(args) and not args[i].isdigit()):
            names.append( args[i][:1].upper() + args[i][1:].lower())
            i += 1

        for name in names:

            days = None
            months = None

            if (len(args) >= i + 1):
                if (len(args) == i + 1 or args[i + 1] in ['month', 'months']): months=int(args[i])
                elif (args[i + 1] in ['day', 'days']): days=int(args[i])
            
            target = attendance.get_participant(name, days=days, months=months)

            if len(target['raids']) is 0:
                message += 'No attended raids registered for **' + name + '**.\n\n'
            else:
                if brief:
                    raider_attendance = str(round(target['attendance'] * 100))
                    attended_raids = str(len(target['raids']))
                    missed_raids = str(len(target['missed_raids']))
                    message += '**{}** - attendance: **{}%**, attended raids: **{}**, missed raids: **{}**.'.format(name, raider_attendance, attended_raids, missed_raids)
                else:
                    message +=  'Attendance for __**' + name + '**__: \n'
                    message += 'Total attendance: **' + str(round(target['attendance'] * 100, 1)) + '%**.\n'

                    attended_raids = [getDateFromtimestamp(raid) for raid in target['raids']]
                    if verbose:
                        message += 'Raids attended (**' + str(len(target['raids'])) + '**): '
                        message += ', '.join(attended_raids) + '\n'
                    else:
                        message += 'Raids attended: **'  + str(len(target['raids'])) + '**\n'
                    
                    missed_raids = [getDateFromtimestamp(raid) for raid in target['missed_raids']]
                    if verbose:
                        message += 'Raids attended (**' + str(len(target['missed_raids'])) + '**): '
                        message += ', '.join(missed_raids) + '\n'
                    else:
                        message += 'Raids missed: **'  + str(len(target['missed_raids'])) + '**\n'
            
            if name != names[-1]:
                message += '\n'

        await ctx.send(content=message)

    elif (len(args) > 0 and args[0] == 'class'):
        guild_raiders = raiders.getRaiders()

        message = ""
        i = 1

        names = {}
        while (i < len(args) and not args[i].isdigit()):
            names[args[i]] = []
            for name in guild_raiders:
                if (guild_raiders[name]['class'].lower() == args[i].lower()): 
                    names[args[i]].append(name[:1].upper() + name[1:].lower())

            i += 1

        for class_name in names:
            message += '__**{}:**__\n'.format(class_name[:1].upper() + class_name[1:].lower())
            for name in names[class_name]:
                days = None
                months = None

                if (len(args) >= i + 1):
                    if (len(args) == i + 1 or args[i + 1] in ['month', 'months']): months=int(args[i])
                    elif (args[i + 1] in ['day', 'days']): days=int(args[i])
                
                target = attendance.get_participant(name, days=days, months=months)

                if len(target['raids']) is 0:
                    message += 'No attended raids registered for ' + name + '.\n'
                else:
                    raider_attendance = str(round(target['attendance'] * 100))
                    attended_raids = str(len(target['raids']))
                    missed_raids = str(len(target['missed_raids']))
                    message += '**{}** - attendance: **{}%**, attended raids: **{}**, missed raids: **{}**.\n'.format(name, raider_attendance, attended_raids, missed_raids)
            message += '\n'
        await ctx.send(content=message)
    else:
        if (len(args) > 0):
            if (len(args) == 1 or args[1] in ['month', 'months']): months=int(args[0])
            elif (args[1] in ['day', 'days']): days=int(args[0])
        participants = attendance.get_participants(days=days, months=months)
        attendance.make_attendance_plot(participants, 'attendance_plot.png')
        await ctx.send(content="Attendance plot: ", file=discord.File(raiders.dir_path + '/attendance_plot.png'))
# HANDLERS
@client.event
async def on_ready():
    try:
        wclRaidTask.start()
        update_raiders_task.start()
        print(timestamp(), 'started tasks')
    except RuntimeError:
        print(timestamp(), 'reconnected')

# 
print(timestamp(), 'starting discord bot with token:', discord_token.strip())
client.run(discord_token.strip())