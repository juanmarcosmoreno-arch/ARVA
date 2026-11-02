import { BarChart, GraphChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

echarts.use([BarChart, GraphChart, HeatmapChart, LineChart, ScatterChart, DataZoomComponent, GridComponent, LegendComponent,
  TooltipComponent, MarkLineComponent, VisualMapComponent, SVGRenderer]);

export { echarts };
