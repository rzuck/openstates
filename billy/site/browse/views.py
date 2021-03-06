import random
from collections import defaultdict

from billy import db
from billy.utils import metadata

from django.http import Http404
from django.views.decorators.cache import never_cache
from django.shortcuts import render_to_response
from django.utils.datastructures import SortedDict


def keyfunc(obj):
    try:
        return int(obj['district'])
    except ValueError:
        return obj['district']


def all_states(request, template='billy/index.html'):
    states = []
    for meta in list(db.metadata.find()) + [{'_id':'total', 'name':'total'}]:
        state = {}
        state['id'] = meta['_id']
        s_spec = {'state': state['id']}
        state['name'] = meta['name']
        counts = db.counts.find_one({'_id': state['id']})
        if counts:
            counts = counts['value']
            state['bills'] = counts['bills']
            state['votes'] = counts['votes']
            state['versions'] = counts['versions']
            if counts['actions']:
                state['typed_actions'] = (float(counts['categorized']) /
                                          counts['actions'] * 100)
            if counts['bills']:
                state['subjects'] = (float(counts['subjects']) /
                                     counts['bills'] * 100)
            if counts['sponsors']:
                state['sponsor_ids'] = (float(counts['idd_sponsors']) /
                                        counts['sponsors'] * 100)
            if counts['voters']:
                state['voter_ids'] = (float(counts['idd_voters']) /
                                      counts['voters'] * 100)

        if state['id'] != 'total':
            state['bill_types'] = len(db.bills.find(s_spec).distinct('type')) > 1
            state['legislators'] = db.legislators.find(s_spec).count()
            state['committees'] = db.committees.find(s_spec).count()
            id_counts = _get_state_leg_id_stats(state['id'])
            active_legs = db.legislators.find({'state': state['id'],
                                               'active': True}).count()

            if not active_legs:
                state['external_ids'] = 0
            else:
                total_missing = float(id_counts['missing_pvs'] +
                                      id_counts['missing_tdata'])
                state['external_ids'] = (1 - (total_missing /
                                              (active_legs * 2))) * 100

            missing_bill_sources = db.bills.find({'state': state['id'],
                                              'sources': {'$size': 0}}).count()
            missing_leg_sources = db.legislators.find({'state': state['id'],
                                              'sources': {'$size': 0}}).count()
            state['missing_sources'] = ''
            if missing_bill_sources:
                state['missing_sources'] += 'bills'
            if missing_leg_sources:
                state['missing_sources'] += ' legislators'
        else:
            state['bill_types'] = 'n/a'
            state['legislators'] = db.legislators.find().count()
            state['committees'] = db.committees.find().count()

        states.append(state)

    states.sort(key=lambda x: x['id'] if x['id'] != 'total' else 'zz')

    return render_to_response(template, {'states': states})


def _bill_stats_for_session(state, session):
    context = {}
    context['upper_bill_count'] = db.bills.find({'state': state,
                                                 'session': session,
                                                 'chamber': 'upper'}).count()
    context['lower_bill_count'] = db.bills.find({'state': state,
                                                 'session': session,
                                                 'chamber': 'lower'}).count()
    context['bill_count'] = (context['upper_bill_count'] +
                             context['lower_bill_count'])
    context['ns_bill_count'] = db.bills.find({'state': state,
                                              'session': session,
                                           'sources': {'$size': 0}}).count()
    types = defaultdict(int)
    action_types = defaultdict(int)
    total_actions = 0
    versions = 0

    for bill in db.bills.find({'state': state, 'session': session},
                              {'type': 1, 'actions.type': 1, 'versions': 1}):
        for t in bill['type']:
            types[t] += 1
        for a in bill['actions']:
            for at in a['type']:
                action_types[at] += 1
                total_actions += 1
        versions += len(bill.get('versions', []))
    context['versions'] = versions

    context['types'] = dict(types)
    context['action_types'] = dict(action_types)
    if total_actions:
        context['action_cat_percent'] = ((total_actions -
                                          action_types['other']) /
                                         float(total_actions) * 100)

    return context


def _get_state_leg_id_stats(state):
    context = {}
    context['missing_pvs'] = db.legislators.find({'state': state,
                             'active': True,
                             'votesmart_id': {'$exists': False}}).count()
    context['missing_nimsp'] = db.legislators.find({'state': state,
                             'active': True,
                             'nimsp_id': {'$exists': False}}).count()
    context['missing_tdata'] = db.legislators.find({'state': state,
         'active': True, 'transparencydata_id': {'$exists': False}}).count()
    return context


def state_index(request, state):
    meta = metadata(state)
    if not meta:
        raise Http404

    context = {}
    context['metadata'] = SortedDict(sorted(meta.items()))

    # types
    latest_session = meta['terms'][-1]['sessions'][-1]
    context['session'] = latest_session

    context.update(_bill_stats_for_session(state, latest_session))

    # legislators
    context['upper_leg_count'] = db.legislators.find({'state': state,
                                                      'active': True,
                                                  'chamber': 'upper'}).count()
    context['lower_leg_count'] = db.legislators.find({'state': state,
                                                      'active': True,
                                                  'chamber': 'lower'}).count()
    context['lower_leg_count'] = db.legislators.find({'state': state,
                                                      'active': True,
                                                  'chamber': 'lower'}).count()
    context['leg_count'] = (context['upper_leg_count'] +
                            context['lower_leg_count'])
    context['inactive_leg_count'] = db.legislators.find({'state': state,
                                                     'active': False}).count()
    context['ns_leg_count'] = db.legislators.find({'state': state,
                             'active': True,
                             'sources': {'$size': 0}}).count()
    context.update(_get_state_leg_id_stats(state))

    # committees
    context['upper_com_count'] = db.committees.find({'state': state,
                                                  'chamber': 'upper'}).count()
    context['lower_com_count'] = db.committees.find({'state': state,
                                                  'chamber': 'lower'}).count()
    context['joint_com_count'] = db.committees.find({'state': state,
                                                  'chamber': 'joint'}).count()
    context['com_count'] = (context['upper_com_count'] +
                            context['lower_com_count'] +
                            context['joint_com_count'])
    context['ns_com_count'] = db.committees.find({'state': state,
                             'sources': {'$size': 0}}).count()

    return render_to_response('billy/state_index.html', context)


def bills(request, state):
    meta = metadata(state)
    if not meta:
        raise Http404

    sessions = []
    for term in meta['terms']:
        for session in term['sessions']:
            stats = _bill_stats_for_session(state, session)
            stats['session'] = session
            sessions.append(stats)

    return render_to_response('billy/bills.html',
                              {'sessions': sessions, 'metadata': meta})


@never_cache
def random_bill(request, state):
    meta = metadata(state)
    if not meta:
        raise Http404
    latest_session = meta['terms'][-1]['sessions'][-1]

    spec = {'state': state.lower(), 'session': latest_session}

    count = db.bills.find(spec).count()
    bill = db.bills.find(spec)[random.randint(0, count - 1)]

    return render_to_response('billy/bill.html', {'bill': bill})


def bill(request, state, session, id):
    bill = db.bills.find_one(dict(state=state.lower(),
                                  session=session,
                                  bill_id=id.upper()))
    if not bill:
        raise Http404

    return render_to_response('billy/bill.html', {'bill': bill})


def legislators(request, state):
    upper_legs = db.legislators.find({'state': state.lower(),
                                      'active': True,
                                      'chamber': 'upper'})
    lower_legs = db.legislators.find({'state': state.lower(),
                                      'active': True,
                                      'chamber': 'lower'})
    inactive_legs = db.legislators.find({'state': state.lower(),
                                         'active': False})
    upper_legs = sorted(upper_legs, key=keyfunc)
    lower_legs = sorted(lower_legs, key=keyfunc)
    inactive_legs = sorted(inactive_legs, key=lambda x: x['last_name'])

    return render_to_response('billy/legislators.html', {
        'upper_legs': upper_legs,
        'lower_legs': lower_legs,
        'inactive_legs': inactive_legs,
        'metadata': metadata(state),
    })


def legislator(request, id):
    leg = db.legislators.find_one({'_all_ids': id})
    if not leg:
        raise Http404
    return render_to_response('billy/legislator.html', {'leg': leg,
                                          'metadata': metadata(leg['state'])})


def committees(request, state):
    upper_coms = db.committees.find({'state': state.lower(),
                                      'chamber': 'upper'})
    lower_coms = db.committees.find({'state': state.lower(),
                                      'chamber': 'lower'})
    joint_coms = db.committees.find({'state': state.lower(),
                                      'chamber': 'joint'})
    upper_coms = sorted(upper_coms)
    lower_coms = sorted(lower_coms)
    joint_coms = sorted(joint_coms)

    return render_to_response('billy/committees.html', {
        'upper_coms': upper_coms,
        'lower_coms': lower_coms,
        'joint_coms': joint_coms,
        'metadata': metadata(state),
    })
