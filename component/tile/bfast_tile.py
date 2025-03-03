from pathlib import Path
from datetime import datetime

import ipyvuetify as v
from sepal_ui import sepalwidgets as sw 

from component import widget as cw
from component.message import cm
from component import scripts as cs
from component import parameter as cp

class BfastTile(sw.Tile):
    
    def __init__(self):
        
        # create the different widgets 
        # I will not use Io as the information doesn't need to be communicated to any other tile
        self.folder = cw.FolderSelect()
        self.out_dir = cw.OutDirSelect()
        self.tiles = cw.TilesSelect()
        self.poly = v.Select(label=cm.widget.harmonic.label, v_model=3, items=[i for i in range(3,11)])
        self.freq = v.Slider(label=cm.widget.freq.label, v_model=365, min=1, max=365, thumb_label="always", class_='mt-5')
        self.trend = v.Switch(v_model=False, label=cm.widget.trend.label)
        self.hfrac = v.Select(label=cm.widget.hfrac.label, v_model=.25, items=[.25, .5, 1.])
        self.level = v.Slider(label=cm.widget.level.label, v_model=.95, step=.001, min=.95, max=1, thumb_label="always", class_='mt-5')
        self.backend = cw.BackendSelect()
        self.monitoring = cw.DateRangeSlider(label=cm.widget.monitoring.label)
        self.history = cw.DateSlider(label=cm.widget.history.label)
        
        # stack the advance parameters in a expandpanel 
        advance_params = v.ExpansionPanels(class_='mb-5', popout=True, children=[
            v.ExpansionPanel(children=[
                v.ExpansionPanelHeader(children=[cm.widget.advance_params]),
                v.ExpansionPanelContent(children=[
                    v.Flex(xs12=True, children=[self.hfrac]),
                    v.Flex(xs12=True, children=[self.level]),
                    v.Flex(xs12=True, children=[self.backend])
                ])
            ])
        ])
        
        # create the tile 
        super().__init__(
            "bfast_tile",
            cm.bfast.folder, # the title is used to describe the first section 
            inputs=[
                self.folder, self.out_dir, self.tiles,
                v.Html(tag="h2", children=[cm.bfast.process]),
                self.poly, self.freq, self.trend, advance_params,
                v.Html(tag="h2", children=[cm.bfast.periods]),
                self.history,self.monitoring
            ],
            output=cw.CustomAlert(),
            btn=sw.Btn(cm.bfast.btn)
        
        )
        
        # add js behaviour 
        self.folder.observe(self._on_folder_change, 'v_model')
        self.btn.on_event('click', self._start_process)
        self.monitoring.observe(self._check_periods, 'v_model')
        self.history.observe(self._check_periods, 'v_model')
        
    def _start_process(self, widget, event, data):
        """start the bfast process"""
        
        widget.toggle_loading()
        
        # gather all the variables for conveniency
        folder = self.folder.v_model
        out_dir = self.out_dir.v_model
        tiles = self.tiles.v_model
        poly = self.poly.v_model
        freq = self.freq.v_model
        trend = self.trend.v_model
        hfrac = self.hfrac.v_model
        level = self.level.v_model
        backend = self.backend.v_model
        monitoring = self.monitoring.v_model
        history = self.history.v_model
        
        # check the inputs 
        if not self.output.check_input(folder, cm.widget.folder.no_folder): return widget.toggle_loading()
        if not self.output.check_input(out_dir, cm.widget.out_dir.no_dir): return widget.toggle_loading()
        if not self.output.check_input(tiles, cm.widget.tiles.no_tiles): return widget.toggle_loading()
        if not self.output.check_input(poly, cm.widget.harmonic.no_poly): return widget.toggle_loading()
        if not self.output.check_input(freq, cm.widget.freq.no_freq): return widget.toggle_loading()
        if not self.output.check_input(trend, cm.widget.trend.no_trend): return widget.toggle_loading()
        if not self.output.check_input(hfrac, cm.widget.hfrac.no_frac): return widget.toggle_loading()
        if not self.output.check_input(level, cm.widget.level.no_level): return widget.toggle_loading()
        if not self.output.check_input(backend, cm.widget.backend.no_backend): return widget.toggle_loading()
        if not self.output.check_input(len(monitoring), cm.widget.monitoring.no_dates): return widget.toggle_loading()
        if not self.output.check_input(history, cm.widget.history.no_date): return widget.toggle_loading()  
        
        # check the dates
        start_history = datetime.strptime(history, "%Y-%m-%d")
        start_monitor = datetime.strptime(monitoring[0], "%Y-%m-%d")
        end_monitor = datetime.strptime(monitoring[1], "%Y-%m-%d")
        
        if not (start_history < start_monitor < end_monitor):
            self.output.add_msg(cm.widget.monitoring.bad_order, 'error')
            return widget.toggle_loading()
        
        try:
            
            # run the bfast process
            cs.run_bfast(Path(folder), out_dir, tiles, monitoring, history, freq, poly, hfrac, trend, level, backend, self.output)
        
            # display the end of computation message
            self.output.add_live_msg(cm.bfast.complete.format(out_dir), 'success')
            
        except Exception as e:
            self.output.add_live_msg(str(e))
        
        widget.toggle_loading()
        
    def _on_folder_change(self, change):
        """
        Change the available tiles according to the selected folder
        Raise an error if the folder is not structured as a SEPAL time series (i.e. folder number for each tile)
        """
        
        # get the new selected folder 
        folder = Path(change['new'])
        
        # reset the widgets
        self.out_dir.v_model = None
        self.tiles.reset()
        
        # check if it's a time series folder 
        if not self.folder.is_valid_ts():
            
            # reset the non working inputs 
            self.monitoring.disable()
            self.history.disable()
            self.tiles.reset()
            
            # display a message to the end user
            self.output.add_msg(cm.widget.folder.no_ts.format(folder), 'warning')
            
            return self
        
        # set the basename
        self.out_dir.set_folder(folder)
        
        # set the items in the dropdown 
        self.tiles.set_items(folder)
        
        # set the dates for the sliders 
        # we consider that the dates are consistent through all the folders so we can use only the first one
        with (folder/'0'/'dates.csv').open() as f:
            dates = [l for l in f.read().splitlines() if l.rstrip()]
            
        self.monitoring.set_dates(dates)
        self.history.set_dates(dates)
        
        self.output.add_msg(cm.widget.folder.valid_ts.format(folder))
        
        return self
    
    def _check_periods(self, change):
        """check if the historical period have enough images"""
        
        # to avoid bug on disable
        if not self.history.dates:
            return self
        
        # get the index of the current history and monitoring dates
        history = self.history.slider.v_model
        monitor = self.monitoring.range.v_model[0]
        
        if history > (monitor - cp.min_images):
            self.output.add_msg(cm.widget.history.too_short, 'warning')
        else:
            self.output.reset()
            
        return self
        
        
        
        