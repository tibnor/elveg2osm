#! /usr/bin/env python2
import sys
import osmapis
import csv
import numpy as np
import geographiclib.geodesic as gg

# Output have the following temporary features:
# - The split nodes have tags newnode=yes
# - Some ways have tags DEBUG=*. Those have Elveg tags I'm unsure about how to tag in OSM.


# Add useful (for our purpose) methods to the osmapis.OSM class
class ElvegOSM(osmapis.OSM):

    def __init__(self, items=()):
        # First call the parent's __init__
        super(ElvegOSM, self).__init__(items)

        # Generate dict with TRANSID as key and is as value
        self.wayid_dict = {}
        for wayid,way in self.ways.iteritems():
            transid = way.tags['TRANSID']
            self.wayid_dict[transid] = wayid

    def way_nodes_from_transid(self, transid):
        wayid = self.wayid_dict[transid]
        way = self.ways[wayid]
        node_ids = way.nds
        nodes = [osmobj.nodes[nid] for nid in node_ids]
        return nodes

    def distances_from_transid(self, transid):
        global g
        nodes = self.way_nodes_from_transid(transid)
        node_distances = []
        distance_so_far = 0.
        prev_lon = nodes[0].lon
        prev_lat = nodes[0].lat
        
        for i,nd in enumerate(nodes):
            #az1,az2,d_from_previous = g.inv(prev_lon, prev_lat, nd.lon, nd.lat)
            ggresults = gg.Geodesic.WGS84.Inverse(prev_lat, prev_lon, nd.lat, nd.lon)
            d_from_previous = ggresults['s12']
            if i != 0 and d_from_previous < 0.5:
                # Report if very short distance
                sys.stderr.write('Short distance ({2}) for transid {0} to node No. {1}\n'.format(transid, i,d_from_previous))
            distance_so_far += d_from_previous
            node_distances.append(distance_so_far)
            # Prepare previous coordinates for next round
            prev_lon = nd.lon
            prev_lat = nd.lat

        return node_distances

class ElvegNode(osmapis.Node):

    def __init__(self, attribs={}, tags={}):
        osmapis.Node.__init__(self, attribs, tags)
        # Make sure the class counter is as low as the lowest existing ID
        # This should probably have been done in osmapis.Node
        if self.id is not None:
            self.__class__._counter = min(self.__class__._counter, self.id)
            
class ElvegWay(osmapis.Way):

    def __init__(self, attribs={}, tags={}, nds=()):
        osmapis.Way.__init__(self, attribs, tags, nds)
        # Make sure the class counter is as low as the lowest existing ID
        # This should probably have been done in osmapis.Way
        if self.id is not None:
            self.__class__._counter = min(self.__class__._counter, self.id)


# Override default classes in osmapis.py
osmapis.wrappers["osm"]  = ElvegOSM
osmapis.wrappers["node"] = ElvegNode
osmapis.wrappers["way"]  = ElvegWay

def warn(warning):
    sys.stderr.write(warning + '\n')

def create_osmtags(elveg_tags):
    '''Create tags based on standard tags in ????Elveg_default.osm'''

    category2highwayclass = {'E': 'trunk',     # Europaveg
                             'R': 'trunk',     # Riksveg
                             'F': 'secondary', # Fylkesveg, could also be primary
                             'K': 'road',      # Kommunal veg
                             'P': 'road',      # Privat veg
                             'S': 'track'}     # Skogsbilveg, possibly more info in the LBVKLASSE tag

    roadOBJTYPEs = set([u'VegSenterlinje', 
                        u'Svingekonnekteringslenke',
                        u'Kj\xf8refelt',
                        u'Kj\xf8rebane'])

    osmtags = dict()

    # Add the nvdb:id tag from the TRANSID tag
    # All ways should have a TRANSID (will change to LOKALID with SOSI 4.5)
    osmtags['nvdb:id'] = elveg_tags['TRANSID']


    # Roads and ferry routes share many tags, and are therefore
    # treated together
    if elveg_tags['OBJTYPE'] in roadOBJTYPEs.union([u'Bilferjestrekning']) :

        # Split VNR tag
        # The "vegnummer" tag is optional, but let's assume it is always present for now
        # (i.e. fix it if it causes problems)
        vegkategori,vegstatus,vegnummer = [s.strip() for s in elveg_tags['VNR'].split(':')]

        # There are more vegstatus values than listed in https://wiki.openstreetmap.org/w/images/c/cc/Elveg_SOSI_4.0_2008.pdf
        # There is a more complete list in chapter 7.3.11 in 
        # http://www.statkart.no/Documents/Standard/SOSI-standarden%20del%201%20og%202/SOSI%20standarden/Vegnett.pdf

        if elveg_tags['OBJTYPE'] in roadOBJTYPEs:
            # Set the road category
            if vegstatus in ['V','T','W']: # Eksisterende veg, Veg med midlertidig status, Midlertidig veg mer enn et aar
                osmtags['highway'] = category2highwayclass[vegkategori]
            elif vegstatus == 'A':
                osmtags['highway'] = 'construction'
                osmtags['construction'] = category2highwayclass[vegkategori]
            elif vegstatus == 'G':
                osmtags['DEBUG'] = u'Veggrunn, ikke trafikkform\xe5l'
            elif vegstatus == 'M':
                osmtags['DEBUG'] = u'M\xf8te- og rasteplasser'
            elif vegstatus in ['P','Q']: # Vedtatt veg, planlagt veg
                osmtags['action'] = 'delete'
            else:
                warn('Unknown vegstatus {0} for TRANSID {1}'.format(vegstatus,elveg_tags['TRANSID']))
        elif elveg_tags['OBJTYPE'] == u'Bilferjestrekning':
            # Set the class for the ferry route
            if vegstatus == 'S':
                osmtags['route'] = 'ferry'
                osmtags['class'] = category2highwayclass[vegkategori]
            elif vegstatus in ['E','F']: # Vedtatt fergestrekning, planlagt fergestrekning
                osmtags['action'] = 'delete'
            else:
                warn('Ferry route with TRANSID {0} has unknown vegstatus {1}'.format(elveg_tags['TRANSID'],vegstatus))

        # Add ref to road kategories Europaveg, Riksveg and Fylkesveg
        if vegkategori == 'E':
            osmtags['ref'] = 'E ' + vegnummer
        elif vegkategori in ['R', 'F']:
            osmtags['ref'] = vegnummer

    # Gang- og sykkelveg. Only a fraction of all of those are in the data. 
    # Nevertheless, include those that are.
    if elveg_tags['OBJTYPE'] == 'GangSykkelVegSenterlinje':
        osmtags['highway'] = 'cycleway'
        osmtags['foot'] = 'yes'

    # Import GATENAVN for any type of way, although it would probably only exist for road objects
    if elveg_tags.has_key('GATENAVN'):
        osmtags['name'] = elveg_tags['GATENAVN']

    # OBJTYPE=Fortau is sometimes used when a Gang- og sykkelveg goes over 
    # in a sidewalk for a while
    # A sidewalk is usually best represented as a sidewalk=* on a road,
    # but at least in the conversion we let it be a separate way.
    if elveg_tags['OBJTYPE'] == 'Fortau':
        osmtags['highway'] = 'footway'
        osmtags['footway'] = 'sidewalk' 
        osmtags['note'] = 'Consider adding sidewalk as a tag on the road'
    

    # TODO: OBJTYPE="Frittst\xe5ende trapp" if they look useful

    # TODO: MEDIUM=L should be brige=yes, layer=1
    # TODO: MEDIUM=U should be tunnel=yes, layer=-1

    # TODO: Add information about lanes from the VKJORFLT tag (oneway=*, lanes=*)

    return osmtags

def split_way(osmobj, way_id, split_points):
    '''Split way at split points.

    Return list of way ids for the split way. The first id is of the
    original way.

    '''
 
   # Do not go through the hassle, if the way needs no splitting
    if len(split_points) == 0:
        return [way_id]

    # Initialize a list of way id's of the new ways (to be returned)
    # Since the last way is always split off first, the list will be
    # in reverse order, and is turned around at the end.
    splitway_id_list = []

    # Get the way that is to be split
    way = osmobj.ways[way_id]
    transid = way.elveg_tags['TRANSID']

    # Compute distances from start to each node of way
    node_distances = osmobj.distances_from_transid(transid)
    geo_length = node_distances[-1]

    # Compute VPA length and normalize split_points to geographic length
    if way.elveg_tags.has_key("VPA"):
        vpa = [int(n) for n in way.elveg_tags["VPA"].split(':')]
    else:
        # These roads are probably not split, so 1.0 is fine, but raise Exception for now
        #corrction_factor = 1.0
        raise KeyError("VPA Elveg tag not present")
    vpa_length = vpa[2] - vpa[1]
    normalization_factor = geo_length / float(vpa_length)
    split_points_normalized = [normalization_factor * sp for sp in split_points]

    # Make sure the normalized split points are sorted
    # (so that we can split off ways from the end of the list)
    split_points_normalized.sort()

    # Loop over the split points, splitting off the last way each time
    while len(split_points_normalized) > 0:
        current_split_point = split_points_normalized.pop()
        upper_split_index = np.searchsorted(node_distances, current_split_point)

        # Find the coordinates for the new split node
        from_node_id = way.nds[upper_split_index - 1]
        to_node_id = way.nds[upper_split_index]
        from_node = osmobj.nodes[from_node_id]
        to_node = osmobj.nodes[to_node_id]
        ggresults = gg.Geodesic.WGS84.Inverse(from_node.lat, from_node.lon, to_node.lat, to_node.lon)
        distance = ggresults['s12']
        azi1 = ggresults['azi1']
        dist_from_last_node = current_split_point - node_distances[upper_split_index - 1]
        ggresults = gg.Geodesic.WGS84.Direct(from_node.lat, from_node.lon, azi1, dist_from_last_node)
        newlon = ggresults['lon2']
        newlat = ggresults['lat2']

        # Create the new node
        split_node = ElvegNode(attribs={"lon": newlon, "lat": newlat})
        if osmobj.nodes.has_key(split_node.id):
            # This should not happen if ElvegNode.__init__() does the right thing
            raise Exception('Almost overwrote node {0}\n'.format(split_node.id))
        osmobj.nodes[split_node.id] = split_node

        # TEMPORARY:
        osmobj.nodes[split_node.id].tags['newnode'] = 'yes'

        # Create a new way from the split_point to the end of the way
        newway_nodes = [split_node.id] + way.nds[upper_split_index:]
        newway = ElvegWay(tags=way.tags, nds=newway_nodes)
        splitway_id_list.append(newway.id)
        osmobj.ways[newway.id] = newway

        # Remove nodes for the new way from the old way
        way.nds = way.nds[:upper_split_index] + [split_node.id]

    # Finally, add the original way, which is the first segment of the
    # newly split way.
    splitway_id_list.append(way_id)

    # Reverse direction so that first way segment comes first
    return splitway_id_list[::-1]

        
# Read input arguments
osm_input = sys.argv[1]
elveg_fart = sys.argv[2]
elveg_hoyde = sys.argv[3]
osm_output = sys.argv[4]

# Loop over speed limits and tags where the whole 
# way where possible. Other places, add to split list
roaddata = {}
with open(elveg_fart, 'rb') as ef:
    # Read first four header lines
    ef_header = ef.next()
    ef_export_line = ef.next()
    ef_some_number = ef.next()
    ef_empty_line = ef.next()
    
    # Then use csv module for reading data
    reader = csv.DictReader(ef, delimiter=';')
    for row in reader:
        transid = row[' TransID']

        fart_start = int(row['Fra'])
        fart_stop =  int(row['   Til'])
        fart_length = fart_stop - fart_start
        fart_limit = row[' Fart']

        if not roaddata.has_key(transid):
            roaddata[transid] = {}
        if not roaddata[transid].has_key('maxspeed'):
            roaddata[transid]['maxspeed'] = []
        roaddata[transid]['maxspeed'].append({'maxspeed': fart_limit,
                                              'start': fart_start,
                                              'stop': fart_stop})
# Add height limits to roaddata
with open(elveg_hoyde, 'rb') as eh:
    # Read first four header lines
    eh_header = eh.next()
    eh_export_line = eh.next()
    eh_empty_line1 = eh.next()
    eh_empty_line2 = eh.next()

    # Then use csv module for reading data
    reader = csv.DictReader(eh, delimiter=';')
    for row in reader:
        transid = row[' TransID']

        height_start = int(row['Fra'])
        height_stop =  int(row['   Til'])
        height_length = height_stop - height_start
        height_limit = row['H\xf8yde']

        if not roaddata.has_key(transid):
            roaddata[transid] = {}
        if not roaddata[transid].has_key('maxheight'):
            roaddata[transid]['maxheight'] = []
        roaddata[transid]['maxheight'].append({'maxheight': height_limit,
                                               'start': height_start,
                                               'stop': height_stop})

# TODO: Add information from XXXXAksel.txt to roadddata,
# and add relevant tagging.

# Read OSM file
osmobj = ElvegOSM.load(osm_input)

# Loop through all ways in osmobj and 
# - swap original tags with OSM tags.
# - extract the way length from the Elveg VPA tag and
#   store in roaddata structure
# Important to use items() instead of iteritems() here as we are adding
# items to the obmobj.ways dictionary during the loop.
for wid,w in osmobj.ways.items():
    # Add new tags (using the create_osmtags function)
    w.elveg_tags = w.tags
    osm_tags = create_osmtags(w.elveg_tags)
    w.tags = osm_tags

    # Add way length as given by VPA to the roadddata structure
    transid = w.elveg_tags['TRANSID']
    vpa = [int(n) for n in w.elveg_tags["VPA"].split(':')]
    # We do not care about those ways where we have no data to add,
    # so move to next if this is the case.
    if not roaddata.has_key(transid):
        continue
    roaddata[transid]['length'] = vpa[2] - vpa[1]
    
    # make a sorted list of meter values, including end
    # points, where some roaddata may change
    end_points = [0, roaddata[transid]['length']]
    for restriction_type in ['maxspeed', 'maxheight']: # Add any new restrictions here
        for endpoint_type in ['start', 'stop']:
            end_points.extend([d[endpoint_type] for d in roaddata[transid].get(restriction_type, [])])
    end_points = list(set(end_points))
    end_points.sort()

    # Make a list of intervals, representing the new ways after a split
    # For most ways, there will be only one interval, but whenever
    # the speed limit changes on a way or a height restriction
    # does not apply to the whole way, there will be more than one interval
    interval_list = zip(end_points[:-1],end_points[1:])

    # Make a list of tags (maxheight=*, maxspeed=*)
    # with one list entry per new way interval
    newway_tags = [{} for i in interval_list] # I.e. a list of empty dicts
    for i,interval in enumerate(interval_list):
        for restriction_type in ['maxspeed', 'maxheight']: # Add any new restrictions here
            for j,restr in enumerate(roaddata[transid].get(restriction_type, [])):
                if restr['start'] <= interval[0] and interval[1] <= restr['stop']:
                    newway_tags[i][restriction_type] = restr[restriction_type]

    # DEBUG: Remove later
    #print newway_tags

    # Split the way in osmobj into the right number of segments
    split_points = end_points[1:-1]
    segment_ids = split_way(osmobj, w.id, split_points)

    # Add nvdb:id:part subkey to each part if the Elveg segment has been split
    if len(segment_ids) > 1:
        for i,segment_id in enumerate(segment_ids):
            osmobj.ways[segment_id].tags['nvdb:id:part'] = str(i)
    
    # Add maxheight and maxspeed restrictions
    for i,segment_id in enumerate(segment_ids):
        osmobj.ways[segment_id].tags.update(newway_tags[i])

    # TODO: Find nodes with VEGSPERRING and merge data with nodes with
    # same location which belong to ways 
    # (the information in XXXXSperr.txt is redundant)

    # TODO: Add amenity="ferry terminal" on nodes with OBJTYPE=Ferjekai

    # TODO: Remove all objects with action=delete

    # TODO: Add turn restrictions from XXXXSving.txt

osmobj.save(osm_output)




