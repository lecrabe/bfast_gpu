import threading
from concurrent import futures
from datetime import datetime
from functools import partial
import time

import rasterio as rio
import numpy as np
from bfast import BFASTMonitor
from bfast.monitor.utils import crop_data_dates
from osgeo import gdal

from component import parameter as cp
from component.message import cm

def break_to_decimal_year(idx, dates):
    """
    break dates of change into decimal year
    build to be vectorized over the resulting bfast break events
    using the following format 
    """
    
    # everything could have been done in a lambda function but for the sake of clarity I prefer to use it 
    if idx < 0:
        return np.nan
    else:
        break_date = dates[idx-1]
        return break_date.year + (break_date.timetuple().tm_yday - 1)/365

def bfast_window(window, read_lock, write_lock, src, dst, segment_dir, monitor_params, crop_params, out):
    """Run the bfast model on image windows"""
    
    # read in a read_lock to avoid duplicate reading and corruption of the data
    with read_lock:
        data = src.read(window=window).astype(np.int16)
        # all the nan are transformed into 0 by casting don't we want to use np.iinfo.minint16 ? 
    
    # read the local observation date
    with (segment_dir/'dates.csv').open() as f:
        dates = [datetime.strptime(l, "%Y-%m-%d") for l in f.read().splitlines() if l.rstrip()]
        
    # crop the initial data to the used dates
    data, dates = crop_data_dates(data,  dates, **crop_params)
    
    # start the bfast process
    model = BFASTMonitor(**monitor_params)
    
    # fit the model 
    model.fit(data, dates)

    # vectorized fonction to format the results as decimal year (e.g mid 2015 will be 2015.5)
    to_decimal = np.vectorize(break_to_decimal_year, excluded=[1])
    
    # slice the date to narrow it to the monitoring dates
    start = monitor_params['start_monitor']
    end = crop_params['end']
    monitoring_dates = dates[dates.index(start):dates.index(end)+1] # carreful slicing is x in [i,j[    
    
    # compute the decimal break on the model 
    decimal_breaks = to_decimal(model.breaks, monitoring_dates)
    
    # agregate the results on 2 bands
    monitoring_results = np.stack((decimal_breaks, model.magnitudes)).astype(np.float32)
    
    with write_lock:
        dst.write(monitoring_results, window=window)   
        out.update_progress()
    
    return
        
def run_bfast(folder, out_dir, tiles, monitoring, history, freq, k, hfrac, trend, level, backend, out):
    """pilot the different threads that will launch the bfast process on windows"""
    
    # prepare parameters for crop as a dict 
    crop_params = {
        'start': datetime.strptime(history, '%Y-%m-%d'),
        'end': datetime.strptime(monitoring[1], '%Y-%m-%d')
    }
        
    # prepare parameters for the bfastmonitor function 
    monitor_params = {
        'start_monitor': datetime.strptime(monitoring[0], '%Y-%m-%d'),
        'freq': freq,
        'k': k,
        'hfrac': hfrac,
        'trend': trend,
        'level': 1-level,  # it's an hidden parameter I hate it https://github.com/diku-dk/bfast/issues/23
        'backend': backend
    }
    
    # create 1 folder for each set of parameter
    parameter_string = f'{history[:4]}_{monitoring[0][:4]}_{monitoring[1][:4]}_k{k}_f{freq}_t{int(trend)}_h{hfrac}_l{level}'
    save_dir = cp.result_dir/out_dir/parameter_string
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # loop through the tiles
    file_list = []
    for tile in tiles:
        
        # get the starting time 
        start = datetime.now()
        
        # get the segment useful folders 
        tile_dir = folder/tile
        tile_save_dir = save_dir/tile
        tile_save_dir.mkdir(exist_ok=True)
        
        # set the log and output file names
        log_file = tile_save_dir/f'tile_{tile}.log'
        file = tile_save_dir/'bfast_outputs.tif'
        
        # check the logs to see if the tile is already finished 
        if log_file.is_file():
            out.add_msg(cm.bfast.skip.format(tile))
            time.sleep(.5) # to let people read the message
            file_list.append(str(file))
            continue
        
        # create the locks to avoid data coruption
        read_lock = threading.Lock()
        write_lock = threading.Lock()

        # get the profile from the master vrt
        with rio.open(tile_dir/'stack.vrt', GEOREF_SOURCES='INTERNAL') as src:
            
            profile = src.profile.copy()
            profile.update(
                driver = 'GTiff',
                count = 2,
                dtype = np.float32
            )
        
            # display an tile computation message
            count = sum(1 for _ in src.block_windows())
            out.add_live_msg(cm.bfast.sum_up.format(count, tile))
            
            # reset the output 
            out.reset_progress(count, cm.bfast.progress.format(tile))
        
            # get the windows
            windows = [w for _, w in src.block_windows()]
            
            # execute the concurent threads and write the results in a dst file 
            with rio.open(file, 'w', **profile) as dst:
                
                bfast_params = {
                    'read_lock': read_lock, 
                    'write_lock': write_lock,
                    'src': src,
                    'dst': dst,
                    'segment_dir': tile_dir, 
                    'monitor_params': monitor_params, 
                    'crop_params': crop_params,
                    'out': out
                }
                
                with futures.ThreadPoolExecutor() as executor: # use all the available CPU/GPU
                    executor.map(partial(bfast_window, **bfast_params), windows)
        
        # write in the logs that the tile is finished
        write_logs(log_file, start, datetime.now())
        
        # add the file to the file_list
        file_list.append(str(file))
        
    # write a global vrt file to open all the tile at one
    vrt_path = save_dir/'bfast_outputs.vrt'
    ds = gdal.BuildVRT(str(vrt_path), file_list)
    ds.FlushCache()
        
    # check that the file was effectively created (gdal doesn't raise errors)
    if not vrt_path.is_file():
        raise Exception(f"the vrt {vrt_path} was not created")
           
    return 

def write_logs(log_file, start, end):
    
    with log_file.open('w') as f: 
        f.write("Computation finished!\n")
        f.write("\n")
        f.write(f"Computation started on: {start} \n")
        f.write(f"Computation finished on: {end}\n")
        f.write("\n")
        f.write(f"Elapsed time: {end-start}")
        
    return
        
        
        