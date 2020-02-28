#
# This file is part of Brazil Data Cube Collection Builder.
# Copyright (C) 2019-2020 INPE.
#
# Brazil Data Cube Collection Builder is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
#

"""Define Brazil Data Cube utils."""


# Python Native
import datetime
import json
import logging
# 3rdparty
from bdc_db.models import Collection, db
from celery import chain, current_task, group
from landsatxplore.api import API
from osgeo import gdal
import requests
# Builder
from ..core.utils import get_credentials
from .models import RadcorActivityHistory
from .sentinel.clients import sentinel_clients


def get_or_create_model(model_class, defaults=None, engine=None, **restrictions):
    """Get or create Brazil Data Cube model.

    Utility method for looking up an object with the given restrictions, creating one if necessary.

    Args:
        model_class (BaseModel) - Base Model of Brazil Data Cube DB
        defaults (dict) - Values to fill out model instance
        restrictions (dict) - Query Restrictions
    Returns:
        BaseModel Retrieves model instance
    """
    if not engine:
        engine = db

    instance = engine.session.query(model_class).filter_by(**restrictions).first()

    if instance:
        return instance, False

    params = dict((k, v) for k, v in restrictions.items())

    params.update(defaults or {})
    instance = model_class(**params)

    engine.session.add(instance)

    return instance, True


def dispatch(activity: dict):
    """Dispatches the activity to the respective celery task handler.

    Args:
        activity (RadcorActivity) - A not done activity
    """
    from .sentinel import tasks as sentinel_tasks
    from .landsat import tasks as landsat_tasks
    # TODO: Implement it as factory (TaskDispatcher) and pass the responsibility to the task type handler

    app = activity.get('activity_type')

    if app == 'downloadS2':
        # We are assuming that collection either TOA or DN
        collection_sr = Collection.query().filter(Collection.id == 'S2SR_SEN28').first()

        if collection_sr is None:
            raise RuntimeError('The collection "S2SR_SEN28" not found')

        # Raw chain represents TOA publish chain
        raw_data_chain = sentinel_tasks.publish_sentinel.s()

        atm_chain = sentinel_tasks.atm_correction.s() | sentinel_tasks.publish_sentinel.s() | \
            sentinel_tasks.upload_sentinel.s()

        task_chain = sentinel_tasks.download_sentinel.s(activity) | \
            group([
                # Publish raw data
                raw_data_chain,
                # ATM Correction
                atm_chain
            ])
        return chain(task_chain).apply_async()
    elif app == 'correctionS2':
        task_chain = sentinel_tasks.atm_correction.s(activity) | \
                        sentinel_tasks.publish_sentinel.s() | \
                        sentinel_tasks.upload_sentinel.s()
        return chain(task_chain).apply_async()
    elif app == 'publishS2':
        tasks = [sentinel_tasks.publish_sentinel.s(activity)]

        if 'S2SR' in activity['collection_id']:
            tasks.append(sentinel_tasks.upload_sentinel.s())

        return chain(*tasks).apply_async()
    elif app == 'downloadLC8':
        # We are assuming that collection DN
        collection_lc8 = Collection.query().filter(Collection.id == 'LC8SR').first()

        if collection_lc8 is None:
            raise RuntimeError('The collection "LC8SR" not found')

        # Raw chain represents DN publish chain
        raw_data_chain = landsat_tasks.publish_landsat.s()

        atm_chain = landsat_tasks.atm_correction_landsat.s() | landsat_tasks.publish_landsat.s() | \
            landsat_tasks.upload_landsat.s()

        task_chain = landsat_tasks.download_landsat.s(activity) | \
            group([
                # Publish raw data
                raw_data_chain,
                # ATM Correction
                atm_chain
            ])
        return chain(task_chain).apply_async()
    elif app == 'correctionLC8':
        task_chain = landsat_tasks.atm_correction_landsat.s(activity) | \
                        landsat_tasks.publish_landsat.s() | \
                        landsat_tasks.upload_landsat.s()
        return chain(task_chain).apply_async()
    elif app == 'publishLC8':
        tasks = [landsat_tasks.publish_landsat.s(activity)]

        if 'LC8SR' in activity['collection_id']:
            tasks.append(landsat_tasks.upload_landsat.s())

        return chain(*tasks).apply_async()
    elif app == 'uploadS2':
        return sentinel_tasks.upload_sentinel.s(activity).apply_async()


def create_wkt(ullon, ullat, lrlon, lrlat):
    """Create WKT representation using lat/long coordinates.

    Args:
        ullon - Upper Left longitude
        ullat - Upper Left Latitude
        lrlon - Lower Right Longitude
        lrlat - Lower Right Latitude

    Returns:
        WKT Object from osr
    """
    from ogr import Geometry, wkbLinearRing, wkbPolygon

    # Create ring
    ring = Geometry(wkbLinearRing)
    ring.AddPoint(ullon, ullat)
    ring.AddPoint(lrlon, ullat)
    ring.AddPoint(lrlon, lrlat)
    ring.AddPoint(ullon, lrlat)
    ring.AddPoint(ullon, ullat)

    # Create polygon
    poly = Geometry(wkbPolygon)
    poly.AddGeometry(ring)

    return poly.ExportToWkt(),poly


def get_landsat_scenes(wlon, nlat, elon, slat, startdate, enddate, cloud, limit):
    """List landsat scenes from USGS."""
    credentials = get_credentials()['landsat']

    api = API(credentials['username'], credentials['password'])

    # Request
    scenes_result = api.search(
        dataset='LANDSAT_8_C1',
        bbox=(slat, wlon, nlat, elon),
        start_date=startdate,
        end_date=enddate,
        max_cloud_cover=cloud or 100
    )

    scenes_output = {}

    for scene in scenes_result:
        if scene['displayId'].endswith('RT'):
            logging.warning('Skipping Real Time {}'.format(scene['displayId']))
            continue

        copy_scene = dict()
        copy_scene['sceneid'] = scene['displayId']
        copy_scene['scene_id'] = scene['entityId']
        copy_scene['cloud'] = int(scene['cloudCover'])
        copy_scene['date'] = scene['acquisitionDate']

        xmin, ymin, xmax, ymax = scene['sceneBounds'].split(',')
        copy_scene['wlon'] = float(xmin)
        copy_scene['slat'] = float(ymin)
        copy_scene['elon'] = float(xmax)
        copy_scene['nlat'] = float(ymax)
        copy_scene['link'] = 'https://earthexplorer.usgs.gov/download/12864/{}/STANDARD/EE'.format(scene['entityId'])

        pathrow = scene['displayId'].split('_')[2]

        copy_scene['path'] = pathrow[:3]
        copy_scene['row'] = pathrow[3:]

        scenes_output[scene['displayId']] = copy_scene

    return scenes_output


def get_sentinel_scenes(wlon,nlat,elon,slat,startdate,enddate,cloud,limit,productType=None):
    """Retrieve Sentinel Images from Copernicus."""
    #    api_hub options:
    #    'https://scihub.copernicus.eu/apihub/' for fast access to recently acquired imagery in the API HUB rolling archive
    #    'https://scihub.copernicus.eu/dhus/' for slower access to the full archive of all acquired imagery
    scenes = {}
    totres = 1000000
    first = 0
    pquery = 'https://scihub.copernicus.eu/dhus/search?format=json'
    pquery = 'https://scihub.copernicus.eu/apihub/search?format=json'
    pquery += '&q=platformname:Sentinel-2'
    if productType is not None:
        pquery += ' AND producttype:{}'.format(productType)
    if enddate is None:
        enddate = datetime.datetime.now().strftime("%Y-%m-%d")
    pquery += ' AND beginposition:[{}T00:00:00.000Z TO {}T23:59:59.999Z]'.format(startdate,enddate)
    pquery += ' AND cloudcoverpercentage:[0 TO {}]'.format(cloud)
    if wlon == elon and slat == nlat:
        pfootprintWkt,footprintPoly = create_wkt(wlon-0.01,nlat+0.01,elon+0.01,slat-0.01)
        pquery += ' AND (footprint:"Contains({})")'.format(footprintPoly)
    else:
        pfootprintWkt,footprintPoly = create_wkt(wlon,nlat,elon,slat)
        pquery += ' AND (footprint:"Intersects({})")'.format(footprintPoly)

    limit = int(limit)
    rows = min(100,limit)
    count_results = 0

    users = sentinel_clients.users

    if not users:
        raise ValueError('No sentinel user set')

    username = list(users)[0]
    password = users[username]['password']

    while count_results < min(limit,totres) and totres != 0:
        rows = min(100,limit-len(scenes),totres)
        first = count_results
        query = pquery + '&rows={}&start={}'.format(rows,first)
        try:
            # Using sentinel user and release on out of scope
            r = requests.get(query, auth=(username, password), verify=True)

            if not r.status_code // 100 == 2:
                logging.exception('openSearchS2SAFE API returned unexpected response {}:'.format(r.status_code))
                return {}
            r_dict = r.json()
            #logging.warning('r_dict - {}'.format(json.dumps(r_dict, indent=2)))

        except requests.exceptions.RequestException as exc:
            return {}

        if 'entry' in r_dict['feed']:
            totres = int(r_dict['feed']['opensearch:totalResults'])
            logging.warning('Results for this feed: {}'.format(totres))
            results = r_dict['feed']['entry']
            #logging.warning('Results: {}'.format(results))
            if not isinstance(results, list):
                results = [results]
            for result in results:
                count_results += 1
                identifier = result['title']
                type = identifier.split('_')[1]
                ### Jump level 2 images (will download and process only L1C)
                if type == 'MSIL2A':
                    logging.warning('openSearchS2SAFE skipping {}'.format(identifier))
                    continue
                scenes[identifier] = {}
                scenes[identifier]['pathrow'] = identifier.split('_')[-2][1:]
                scenes[identifier]['sceneid'] = identifier
                scenes[identifier]['type'] = identifier.split('_')[1]
                for data in result['date']:
                    if str(data['name']) == 'beginposition':
                        scenes[identifier]['date'] = str(data['content'])[0:10]
                if not isinstance(result['double'], list):
                    result['double'] = [result['double']]
                for data in result['double']:
                    if str(data['name']) == 'cloudcoverpercentage':
                        scenes[identifier]['cloud'] = float(data['content'])
                for data in result['str']:
                    if str(data['name']) == 'size':
                        scenes[identifier]['size'] = data['content']
                    if str(data['name']) == 'footprint':
                        scenes[identifier]['footprint'] = data['content']
                    if str(data['name']) == 'tileid':
                        scenes[identifier]['tileid'] = data['content']
                if 'tileid' not in scenes[identifier]:
                    logging.warning( 'openSearchS2SAFE identifier - {} - tileid {} was not found'.format(identifier,scenes[identifier]['pathrow']))
                    logging.warning(json.dumps(scenes[identifier], indent=4))
                scenes[identifier]['link'] = result['link'][0]['href']
                scenes[identifier]['icon'] = result['link'][2]['href']
        else:
            totres = 0
    return scenes


def is_valid_tif(input_data_set_path):
    """Validate Tif.

    Args:
        input_data_set_path (str) - Path to the input data set
    Returns:
        True if tif is valid, False otherwise
    """
    # this allows GDAL to throw Python Exceptions
    gdal.UseExceptions()

    try:
        ds  = gdal.Open(input_data_set_path)
        srcband = ds.GetRasterBand(1)

        array = srcband.ReadAsArray()

        # Check if min == max
        if(array.min() == array.max()):
            del ds
            return False
        del ds
        return True
    except RuntimeError as e:
        logging.error('Unable to open {} {}'.format(input_data_set_path, e))
        return False
