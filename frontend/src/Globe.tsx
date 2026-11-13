import {
  ArcType,
  buildModuleUrl,
  Cartesian2,
  Cartesian3,
  Color,
  HorizontalOrigin,
  ImageryLayer,
  TileMapServiceImageryProvider,
  LabelStyle,
  Rectangle,
  SingleTileImageryProvider,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  UrlTemplateImageryProvider,
  Viewer,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { useEffect, useRef } from "react";
import { easaPair, type Corridor, type Level, type Track } from "./api";
import { zoneImage } from "./zone";

// Natural Earth II ships inside Cesium: no Cesium ion account, no token, works offline.
function naturalEarth(): ImageryLayer {
  return ImageryLayer.fromProviderAsync(
    TileMapServiceImageryProvider.fromUrl(buildModuleUrl("Assets/Textures/NaturalEarthII")),
  );
}

// Optional sharper map: NASA Blue Marble from GIBS, free, no account, ~600 m per pixel at
// level 8 (Natural Earth is ~20 km). Online only: Natural Earth stays underneath as fallback.
function blueMarble(): ImageryLayer {
  return new ImageryLayer(
    new UrlTemplateImageryProvider({
      url:
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry" +
        "/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg",
      maximumLevel: 8,
      credit: "Imagery: NASA GIBS / Blue Marble",
    }),
  );
}

// Camera height when flying to a notice: high enough to see several orbits.
const VIEW_HEIGHT_M = 15_000_000;

// The zone image covers the whole Earth; NEAREST keeps the 0.5° cells square and honest.
function zoneLayer(corridor: Corridor, level: Level, easa: boolean): ImageryLayer {
  const strip = easa ? easaPair(corridor, level) : undefined;
  const layer = ImageryLayer.fromProviderAsync(
    SingleTileImageryProvider.fromUrl(zoneImage(corridor, level, strip).toDataURL(), {
      rectangle: Rectangle.fromDegrees(-180, -90, 180, 90),
    }),
    {
      magnificationFilter: TextureMagnificationFilter.NEAREST,
      minificationFilter: TextureMinificationFilter.NEAREST,
    },
  );
  return layer;
}

// Zones cross-fade when the notice or the step changes, so the shrinking reads as one movement.
const FADE_MS = 700;
const FADE_OUT_DELAY_MS = 300;

const fading = new WeakMap<ImageryLayer, number>(); // newest fade wins on quick clicks

function fade(layer: ImageryLayer, from: number, to: number, done?: () => void): void {
  const start = performance.now();
  fading.set(layer, start);
  const tick = (now: number) => {
    if (fading.get(layer) !== start) return;
    const k = Math.min(1, (now - start) / FADE_MS);
    layer.alpha = from + (to - from) * k;
    if (k < 1) requestAnimationFrame(tick);
    else done?.();
  };
  layer.alpha = from;
  requestAnimationFrame(tick);
}

export interface Landed {
  lat: number;
  lon: number;
  label: string;
}

interface Props {
  track: Track | null;
  corridor: Corridor | null;
  level: Level | null; // null = route only, no zone
  easa: boolean; // outline today's EASA strip over the zone
  landed: Landed | null; // where it really came down (held back until the end of a replay)
  focus: { lat: number; lon: number; seconds: number } | null; // replay: the camera glides here
  sharp: boolean; // NASA Blue Marble over Natural Earth (needs internet)
}

export default function Globe({ track, corridor, level, easa, landed, focus, sharp }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const flownTo = useRef<number | null>(null); // NORAD id the camera last flew to

  useEffect(() => {
    const v = new Viewer(container.current!, {
      baseLayer: naturalEarth(),
      // Widgets that need Cesium ion (geocoder, imagery picker) or that we do not use yet.
      baseLayerPicker: false,
      geocoder: false,
      animation: false,
      timeline: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      homeButton: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      // Draw at the screen's real pixels: on a Windows laptop at 125-150 % scaling Cesium
      // otherwise renders smaller and stretches, blurring the map, the route and the labels.
      useBrowserRecommendedResolution: false,
    });
    viewer.current = v;
    return () => {
      viewer.current = null;
      v.destroy();
    };
  }, []);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !sharp) return;
    const layer = blueMarble();
    v.imageryLayers.add(layer, 1); // just above Natural Earth, below every zone
    return () => {
      if (!v.isDestroyed()) v.imageryLayers.remove(layer, true);
    };
  }, [sharp]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !track) return;

    // Geodesic arcs follow the globe and cross the antimeridian without breaking.
    const route = v.entities.add({
      polyline: {
        positions: Cartesian3.fromDegreesArray(track.points.flatMap(([lat, lon]) => [lon, lat])),
        width: 2,
        material: Color.GOLD.withAlpha(0.8),
        arcType: ArcType.GEODESIC,
      },
    });
    const { lat, lon } = track.impact;
    const centre = v.entities.add({
      position: Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: 12,
        color: Color.RED,
        outlineColor: Color.WHITE,
        outlineWidth: 2,
      },
    });
    // Fly only when the object changes: between notices of one object the camera stays
    // still, so the zone can be seen shrinking in place.
    if (track.norad_id !== flownTo.current) {
      flownTo.current = track.norad_id;
      v.camera.flyTo({
        destination: Cartesian3.fromDegrees(lon, lat, VIEW_HEIGHT_M),
        duration: 1.5,
      });
    }
    return () => {
      if (v.isDestroyed()) return;
      v.entities.remove(route);
      v.entities.remove(centre);
    };
  }, [track]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !corridor || level === null) return;
    const layer = zoneLayer(corridor, level, easa);
    layer.alpha = 0;
    v.imageryLayers.add(layer);
    // The image takes a moment to be ready: fade in only then, or it pops in late.
    const stopWaiting = layer.readyEvent.addEventListener(() => fade(layer, 0, 1));
    return () => {
      stopWaiting();
      // The old zone lingers until the new one is drawn, so the globe is never left empty.
      setTimeout(() => {
        if (!v.isDestroyed())
          fade(
            layer,
            layer.alpha,
            0,
            () => !v.isDestroyed() && v.imageryLayers.remove(layer, true),
          );
      }, FADE_OUT_DELAY_MS);
    };
  }, [corridor, level, easa]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !landed) return;
    const mark = v.entities.add({
      position: Cartesian3.fromDegrees(landed.lon, landed.lat),
      point: { pixelSize: 16, color: Color.WHITE, outlineColor: Color.BLACK, outlineWidth: 3 },
      label: {
        text: landed.label,
        font: "bold 18px system-ui",
        fillColor: Color.WHITE,
        outlineColor: Color.BLACK,
        outlineWidth: 4,
        style: LabelStyle.FILL_AND_OUTLINE,
        horizontalOrigin: HorizontalOrigin.LEFT,
        pixelOffset: new Cartesian2(14, 0),
      },
    });
    return () => {
      if (!v.isDestroyed()) v.entities.remove(mark);
    };
  }, [landed]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !focus) return;
    const height = v.camera.positionCartographic.height; // keep the zoom the user chose
    v.camera.flyTo({
      destination: Cartesian3.fromDegrees(focus.lon, focus.lat, height),
      duration: focus.seconds,
    });
  }, [focus]);

  return <div ref={container} style={{ position: "absolute", inset: 0 }} />;
}
