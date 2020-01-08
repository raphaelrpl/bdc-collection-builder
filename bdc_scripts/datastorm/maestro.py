# Python
from typing import List
import datetime
# 3rdparty
from geoalchemy2 import func
from stac import STAC
import numpy
# BDC Scripts
from bdc_db.models import Collection, Tile, Band, db


def days_in_month(date):
    year = int(date.split('-')[0])
    month = int(date.split('-')[1])
    nday = day = int(date.split('-')[2])
    if month == 12:
        nmonth = 1
        nyear = year +1
    else:
        nmonth = month + 1
        nyear = year
    ndate = '{0:4d}-{1:02d}-{2:02d}'.format(nyear,nmonth,nday)
    td = numpy.datetime64(ndate) - numpy.datetime64(date)
    return td


def decode_path_row(tileid):
    parts = tileid.split(';')
    dpathrow = []
    for part in parts:
        pieces = part.split(',')
        if len(pieces) == 1: return [tileid]
        if len(pieces) != 2:
            return []
        paths = pieces[0].split(':')
        rows  = pieces[1].split(':')
        if len(paths) > 1:
            p1 = int(paths[0])
            p2 = int(paths[1]) + 1
        else:
            p1 = int(paths[0])
            p2 = p1 + 1
        if len(rows) > 1:
            r1 = int(rows[0])
            r2 = int(rows[1]) + 1
        else:
            r1 = int(rows[0])
            r2 = r1 + 1
        for p in range(p1,p2):
            for r in range(r1,r2):
                if (p,r) not in dpathrow:
                    tileid = '{0:03d}{1:03d}'.format(p,r)
                    dpathrow.append(tileid)
    return dpathrow


def decode_periods(temporalschema,startdate,enddate,timestep):
    print('decode_periods - {} {} {} {}'.format(temporalschema,startdate,enddate,timestep))
    requestedperiods = {}
    if startdate is None:
        return requestedperiods
    if isinstance(startdate, datetime.date):
        startdate = startdate.strftime('%Y-%m-%d')

    tdtimestep = datetime.timedelta(days=timestep)
    stepsperperiod = int(round(365./timestep))

    if enddate is None:
        enddate = datetime.datetime.now().strftime('%Y-%m-%d')
    if isinstance(enddate, datetime.date):
        enddate = enddate.strftime('%Y-%m-%d')

    if temporalschema is None:
        periodkey = startdate + '_' + startdate + '_' + enddate
        requestedperiod = []
        requestedperiod.append(periodkey)
        requestedperiods[startdate] = requestedperiod
        return requestedperiods

    if temporalschema == 'M':
        start_date = numpy.datetime64(startdate)
        end_date = numpy.datetime64(enddate)
        requestedperiod = []
        while start_date <= end_date:
            next_date = start_date + days_in_month(str(start_date))
            periodkey = str(start_date)[:10] + '_' + str(start_date)[:10] + '_' + str(next_date - numpy.timedelta64(1, 'D'))[:10]
            requestedperiod.append(periodkey)
            requestedperiods[startdate] = requestedperiod
            start_date = next_date
        return requestedperiods

    # Find the exact startdate based on periods that start on yyyy-01-01
    firstyear = startdate.split('-')[0]
    start_date = datetime.datetime.strptime(startdate, '%Y-%m-%d')
    if temporalschema == 'A':
        dbase = datetime.datetime.strptime(firstyear+'-01-01', '%Y-%m-%d')
        while dbase < start_date:
            dbase += tdtimestep
        if dbase > start_date:
            dbase -= tdtimestep
        startdate = dbase.strftime('%Y-%m-%d')
        start_date = dbase

    # Find the exact enddate based on periods that start on yyyy-01-01
    lastyear = enddate.split('-')[0]
    end_date = datetime.datetime.strptime(enddate, '%Y-%m-%d')
    if temporalschema == 'A':
        dbase = datetime.datetime.strptime(lastyear+'-12-31', '%Y-%m-%d')
        while dbase > end_date:
            dbase -= tdtimestep
        end_date = dbase
        if end_date == start_date:
            end_date += tdtimestep - datetime.timedelta(days=1)
        enddate = end_date.strftime('%Y-%m-%d')

    # For annual periods
    if temporalschema == 'A':
        dbase = start_date
        yearold = dbase.year
        count = 0
        requestedperiod = []
        while dbase < end_date:
            if yearold != dbase.year:
                dbase = datetime.datetime(dbase.year,1,1)
            yearold = dbase.year
            dstart = dbase
            dend = dbase + tdtimestep - datetime.timedelta(days=1)
            dend = min(datetime.datetime(dbase.year,12,31),dend)
            basedate = dbase.strftime('%Y-%m-%d')
            startdate = dstart.strftime('%Y-%m-%d')
            enddate = dend.strftime('%Y-%m-%d')
            periodkey = basedate + '_' + startdate + '_' + enddate
            if count % stepsperperiod == 0:
                count = 0
                requestedperiod = []
                requestedperiods[basedate] = requestedperiod
            requestedperiod.append(periodkey)
            count += 1
            dbase += tdtimestep
        if len(requestedperiods) == 0 and count > 0:
            requestedperiods[basedate].append(requestedperiod)
    else:
        yeari = start_date.year
        yearf = end_date.year
        monthi = start_date.month
        monthf = end_date.month
        dayi = start_date.day
        dayf = end_date.day
        print('decode_periods - {} {} {} {} {} {}'.format(yeari,yearf,monthi,monthf,dayi,dayf))
        for year in range(yeari,yearf+1):
            dbase = datetime.datetime(year,monthi,dayi)
            if monthi <= monthf:
                dbasen = datetime.datetime(year,monthf,dayf)
            else:
                dbasen = datetime.datetime(year+1,monthf,dayf)
            while dbase < dbasen:
                dstart = dbase
                dend = dbase + tdtimestep - datetime.timedelta(days=1)
                basedate = dbase.strftime('%Y-%m-%d')
                startdate = dstart.strftime('%Y-%m-%d')
                enddate = dend.strftime('%Y-%m-%d')
                periodkey = basedate + '_' + startdate + '_' + enddate
                requestedperiod = []
                requestedperiods[basedate] = requestedperiod
                requestedperiods[basedate].append(periodkey)
                dbase += tdtimestep
    return requestedperiods


def search_stac(collection: str):
    return dict(
        extent=dict(
            spatial=[-67.1244739337792, -66.5838, 167.661, -3.52957589337603],
            temporal=[
                "2016-09-01",
                "2019-08-31"
            ]
        )
    )


stac_cli = STAC('http://brazildatacube.dpi.inpe.br/bdc-stac/0.7.0/')


class Maestro:
    datacube = None
    bands = []
    tiles = []
    mosaics = dict()

    def __init__(self, datacube: str, collections: List[str], tiles: List[str], start_date: str, end_date: str):
        self.params = dict(
            datacube=datacube,
            collections=collections,
            tiles=tiles,
            start_date=start_date,
            end_date=end_date
        )

    def orchestrate(self):
        self.datacube = Collection.query().filter(Collection.id == self.params['datacube']).first()

        temporal_schema = self.datacube.temporal_composition_schema.temporal_schema
        temporal_step = self.datacube.temporal_composition_schema.temporal_composite_t
        datacube_stac = stac_cli.collection(self.datacube.id)
        cube_start_date, cube_end_date = datacube_stac['extent']['temporal']

        periodlist = decode_periods(temporal_schema, cube_start_date, cube_end_date, int(temporal_step))

        where = [Tile.grs_schema_id == self.datacube.grs_schema_id]

        if self.params.get('tiles'):
            where.append(Tile.id.in_(self.params['tiles']))

        self.tiles = Tile.query().filter(*where).all()

        self.bands = Band.query().filter(Band.collection_id == self.datacube.id).all()

        dstart = self.params['start_date'] if 'start_date' in self.params else None
        dend = self.params['end_date'] if 'end_date' in self.params else None

        number_cols = self.datacube.raster_size_schemas.raster_size_x
        number_rows = self.datacube.raster_size_schemas.raster_size_y

        for tile in self.tiles:
            self.mosaics[tile.id] = dict(
                periods=dict()
            )

            for datekey in sorted(periodlist):
                requestedperiod = periodlist[datekey]
                for periodkey in requestedperiod:
                    _ , startdate, enddate = periodkey.split('_')

                    if dstart is not None and startdate < dstart:
                        continue
                    if dend is not None and enddate > dend:
                        continue

                    self.mosaics[tile.id]['periods'][periodkey] = {}
                    self.mosaics[tile.id]['periods'][periodkey]['start'] = startdate
                    self.mosaics[tile.id]['periods'][periodkey]['end'] = enddate
                    self.mosaics[tile.id]['periods'][periodkey]['cols'] = number_cols
                    self.mosaics[tile.id]['periods'][periodkey]['rows'] = number_rows
                    self.mosaics[tile.id]['periods'][periodkey]['dirname']  = '{}/{}/{}-{}/'.format(self.datacube.id, tile.id, startdate, enddate)

    @property
    def warped_datacube(self):
        datacube_warped = self.datacube.id

        for fn in ['MEDIAN', 'STACK']:
            datacube_warped = datacube_warped.replace(fn, 'WARPED')

        return Collection.query().filter(Collection.id == datacube_warped).first()

    @property
    def datacube_bands(self):
        if self.params.get('bands'):
            return list(filter(lambda band: band.id in self.params['bands'], self.bands))
        return self.bands

    def prepare_merge(self):
        for tileid in self.mosaics:
            if len(self.mosaics) != 1:
                self.params['tileid'] = tileid
                continue

            bbox_result = db.session.query(
                Tile.id,
                func.ST_AsText(func.ST_BoundingDiagonal(func.ST_Force2D(Tile.geom_wgs84)))
            ).filter(
                Tile.id == tileid
            ).first()

            bbox = bbox_result[1][bbox_result[1].find('(') + 1:bbox_result[0].find(')')]
            bbox = bbox.replace(' ', ',')

            for periodkey in self.mosaics[tileid]['periods']:
                start = self.mosaics[tileid]['periods'][periodkey]['start']
                end = self.mosaics[tileid]['periods'][periodkey]['end']
                # activity['dirname'] = self.mosaics[tileid]['periods'][periodkey]['dirname']

                # Search all images
                self.mosaics[tileid]['periods'][periodkey]['scenes'] = self.search_images(bbox, start, end)

    @staticmethod
    def create_activity(collection: str, scene: str, activity_type: str, scene_type: str, band: str, **parameters):
        return dict(
            band=band,
            collection_id=collection,
            activity_type=activity_type,
            tags=parameters.get('tags', []),
            sceneid=scene,
            scene_type=scene_type,
            args=parameters
        )

    def dispatch_celery(self):
        from celery import group, chain
        from bdc_scripts.datastorm.tasks import blend, warp_merge, publish
        self.prepare_merge()

        bands = self.datacube_bands
        warped_datacube = self.warped_datacube.id

        for tileid in self.mosaics:
            blends = []

            tile = next(filter(lambda t: t.id == tileid, self.tiles))

            # For each blend
            for period in self.mosaics[tileid]['periods']:
                merges_tasks = []

                cols = self.mosaics[tileid]['periods'][period]['cols']
                rows = self.mosaics[tileid]['periods'][period]['rows']

                for band in bands:
                    collections = self.mosaics[tileid]['periods'][period]['scenes'][band.common_name]

                    for collection, merges in collections.items():
                        for merge_date, assets in merges.items():
                            kwargs = dict(
                                date=merge_date,
                                dataset=collection,
                                xmin=tile.min_x,
                                ymax=tile.max_y
                            )
                            task = warp_merge.s(warped_datacube, tileid, period, assets, cols, rows, **kwargs)
                            merges_tasks.append(task)

                task = chain(group(merges_tasks), blend.s())
                blends.append(task)

            task = chain(group(blends), publish.s())
            task.apply_async()

    def search_images(self, bbox: str, start: str, end: str):
        scenes = {}
        options = dict(
            bbox=bbox,
            time='{}/{}'.format(start, end),
            limit=100000
        )

        bands = self.datacube_bands

        for band in bands:
            scenes[band.common_name] = dict()

        for dataset in self.params['collections']:
            collection_metadata = stac_cli.collection(dataset)

            collection_bands = collection_metadata['properties']['bdc:bands']

            items = stac_cli.collection_items(dataset, filter=options)

            for feature in items['features']:
                if feature['type'] == 'Feature':
                    date = feature['properties']['datetime'][0:10]
                    identifier = feature['id']
                    tile = feature['properties']['bdc:tile']

                    for band in bands:
                        if band.common_name not in feature['assets']:
                            continue

                        scenes[band.common_name].setdefault(dataset, dict())

                        link = feature['assets'][band.common_name]['href']

                        # radiometric_processing = linfeature['radiometric_processing']
                        # if radiometric_processing == 'DN' or radiometric_processing == 'TOA': continue

                        scene = {**collection_bands[band.common_name]}
                        scene['sceneid'] = identifier
                        scene['tile'] = tile
                        scene['date'] = date
                        scene['band'] = band.common_name
                        scene['link'] = link

                        if dataset == 'MOD13Q1' and band.common_name == 'quality':
                            scene['link'] = scene['link'].replace('quality','reliability')

                        scenes[band.common_name][dataset].setdefault(date, [])
                        scenes[band.common_name][dataset][date].append(scene)

        return scenes