import json
import os
import argparse
from http.client import HTTPConnection
from datetime import date

VERBOSE = False


def vinput(prompt, validator, default=None):
    if default:
        prompt = prompt + ' [' + default + ']:'
    else:
        prompt += ':'
    print(prompt)
    rawin = input('\t--> ').rstrip()
    val = validator(rawin)
    while rawin and val is False:
        rawin = input('\t--> ').rstrip()
        val = validator(rawin)
    if rawin or not default:
        return rawin
    else:
        return default


def is_integer(s, silence=False):
    try:
        int(s)
        return s
    except ValueError:
        return False


def download_regionals(year):
    conn = HTTPConnection('www.thebluealliance.com')
    conn.request('GET', '/api/v1/events/list?year=' + year)

    r = conn.getresponse()
    answer = r.read().decode('utf-8')
    return answer


def download_match(m, quiet=False):
    conn = HTTPConnection('www.thebluealliance.com')
    conn.request('GET', '/api/v1/match/details?match=' + m)

    r = conn.getresponse()
    answer = r.read().decode('utf-8')
    return answer


def regional_input(search_from, prompt):
    search = vinput(prompt, lambda s: s)

    matches = []

    for k in search_from:
        if (k['short_name'] and search.lower() in k['short_name'].lower()) or search.lower() in k['name'].lower():
            matches.append(k)

    print('\nResults:')
    index = 1
    for m in matches:
        print('\t' + str(index) + '. ' + (m['short_name'] or m['name']) + ' on ' + m['start_date'])
        index += 1

    number = vinput('\nEnter regional number', is_integer, '1')

    return matches[int(number) - 1]


def cache_or_get_json(name, func, *args, **kwargs):
    quiet = False

    if 'quiet' in kwargs:
        quiet = kwargs['quiet']

    if not os.path.isdir('cache'):
        os.mkdir('cache')

    filename = 'cache/' + name + '.json'

    if os.path.exists(filename):
        if not quiet and VERBOSE:
            print('Using cached: ' + name)
        return json.loads(open(filename, 'r').read())
    else:
        if not quiet and VERBOSE:
            print('Generating: ' + name)
        value = func(*args)
        open(filename, 'w').write(value)
        return json.loads(value)


def download_regional(key, quiet=False):
    if not quiet:
        print('Downloading event details...')

    conn = HTTPConnection('www.thebluealliance.com')

    conn.request('GET', '/api/v1/event/details?event=' + key)

    r = conn.getresponse()

    answer = r.read().decode('utf-8')
    return answer


def download_teams(r, quiet=False):
    reg_teams = r['teams']

    to_api = ','.join(reg_teams)
    if not quiet:
        print('Downloading team details...')

    conn = HTTPConnection('www.thebluealliance.com')
    conn.request('GET', '/api/v1/teams/show?teams=' + to_api)
    r = conn.getresponse()

    answer = r.read().decode('utf-8')

    return answer


class Team:
    def __init__(self, number, name, website, location, first_regional):
        self.number = number
        self.name = name
        self.website = website
        self.location = location
        self.regionals = [first_regional, ]
        self.elimcount = 0
        self.elimtotal = 0

        self.qualscount = 0
        self.qualstotal = 0

    def __str__(self):
        return self.number + ': ' + self.name

    def elimaverage(self):
        if self.elimcount:
            return self.elimtotal / self.elimcount
        else:
            return 0

    def qualsaverage(self):
        if self.qualscount:
            return self.qualstotal / self.qualscount
        else:
            return 0

    def average(self):
        if self.qualscount and not self.elimcount:
            return self.qualsaverage()
        elif self.qualscount and self.elimcount:
            return (self.qualstotal + self.elimtotal) / (self.qualscount + self.elimcount)
        else:
            # No data. Team didn't play last year.
            return 0

    def attended(self, regional):
        return ('frc' + str(self.number)) in regional['teams']


# Resolves a list of teams from the regional.
def make_teams(regionals):
    teams = {}

    # For percentage calculation.
    total = len(regionals)

    prevpercent = 0

    counter = 0

    for r in regionals:
        teams_json = cache_or_get_json('teams' + r['key'], download_teams, r, True)
        for tt in teams_json:
            team_number = int(tt['team_number'])
            if team_number not in teams:
                teams[team_number] = Team(tt['team_number'], tt['nickname'], tt['website'], tt['location'], r['name'])
            else:
                teams[team_number].regionals.append(r['name'])

        counter += 1
        percentage = int((counter / total) * 100)
        if (percentage - prevpercent) >= 5:
            print(str(percentage) + '%')
            prevpercent = percentage

    return teams


def make_regionals(regionals_gen):
    regionals = []

    # For percentage calculation.
    total = len(regionals_gen)

    prevpercent = 0

    counter = 0

    for r in regionals_gen:
        regionals.append(cache_or_get_json('regional' + r['key'], download_regional, r['key'], True))

        counter += 1
        percentage = int((counter / total) * 100)
        if (percentage - prevpercent) >= 5:
            print(str(percentage) + '%')
            prevpercent = percentage
    return regionals


# Filter to only necessary regionals to perform calculations (less hammering
# the server and shorter download times)
def filter_regionals(regionals, att_teams):
    newregionals = []
    for r in regionals:
        for t in att_teams.values():
            if t.attended(r):
                newregionals.append(r)
                # We don't want to add the same regional many times.
                break
    return newregionals


def flatten_matches(regionals):
    flattened_matches = []
    for r in regionals:
        for s in r['matches']:
            flattened_matches.append(s)
    return flattened_matches


def correlate_matches(teams, matches):
    # For percentage calculation.
    total = len(matches)

    prevpercent = 0

    counter = 0

    for m in matches:
        # For some reason, matches are returned as a list with the dict as the first argument.
        mjson = cache_or_get_json('match' + m, download_match, m)[0]
        red_score = mjson['alliances']['red']['score']
        blue_score = mjson['alliances']['blue']['score']

        red = mjson['alliances']['red']['teams']
        blue = mjson['alliances']['blue']['teams']

        for r, b in zip(red, blue):
            r = int(r.replace("frc", ""))
            b = int(b.replace("frc", ""))

            if r in teams:
                if mjson['competition_level'] != 'Quals':
                    teams[r].elimtotal += red_score
                    teams[r].elimcount += 1
                else:
                    teams[r].qualstotal += red_score
                    teams[r].qualscount += 1

            if b in teams:
                if mjson['competition_level'] != 'Quals':
                    teams[b].elimtotal += blue_score
                    teams[b].elimcount += 1
                else:
                    teams[b].qualstotal += blue_score
                    teams[b].qualscount += 1

        counter += 1

        percentage = int((counter / total) * 100)

        if (percentage - prevpercent) >= 5:
            print(str(percentage) + '%')
            prevpercent = percentage


def mk_csv(headers, functions, outfname, item_list):
    outf = open(outfname, 'w')

    outf.write(','.join(headers) + ',\n')

    for t in item_list:
        for h in functions:
            val = h(t)
            if val:
                outf.write("\"" + str(val).replace('"', '') + '\",')
            else:
                outf.write(',')
        outf.write('\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', help='Shows caching messages.', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        print('Verbosity enabled.')
        global VERBOSE
        VERBOSE = True


    year = vinput('Enter research year', is_integer)

    regionals_gen = cache_or_get_json('regionals' + year, download_regionals, year)
    regionals_gen = [r for r in regionals_gen if r['official']]
    regionals = make_regionals(regionals_gen)

    # Calculate the current competition year. If it's after April, competition
    # Season is over and scouting is being done for next year.
    today = date.today()
    current_compyear = today.year
    if today.month > 4:
        current_compyear += 1

    # Get regionals that are being attended by the team.
    attended = []

    # Regionals in current competition year
    current_regionals = cache_or_get_json('regionals' + str(current_compyear), download_regionals,
                                          str(current_compyear))

    attended.append(regional_input(current_regionals, 'Enter first regional (search)'))

    prompt = True

    choice = vinput('Type y if you would like to enter another regional, n if not', lambda s: s == 'y' or s == 'n', 'n')

    if choice == 'n':
        prompt = False

    while prompt:
        attended.append(regional_input(current_regionals, 'Enter additional regional (search)'))
        choice = vinput('Type y if you would like to enter another regional, n if not', lambda s: s == 'y' or s == 'n',
                        'n')
        if choice == 'n':
            prompt = False

    attended = [cache_or_get_json('regional' + r['key'], download_regional, r['key']) for r in attended]

    att_teams = make_teams(attended)

    regionals = filter_regionals(regionals, att_teams)

    matches = flatten_matches(regionals)

    correlate_matches(att_teams, matches)

    mk_csv(['Team Number', 'Name', year + ' Elimination Average', year + ' Quals Average', year + ' Total Average', 'Website', 'Location', 'Regionals in ' + str(current_compyear)],
           [lambda self: self.number,
            lambda self: self.name,
            Team.elimaverage,
            Team.qualsaverage,
            Team.average,
            lambda self: self.website,
            lambda self: self.location,
            lambda self: ','.join(
                self.regionals)],
           vinput('Enter output filename', lambda s: '.' in s, 'output.csv'), att_teams.values())


if __name__ == '__main__':
    main()
