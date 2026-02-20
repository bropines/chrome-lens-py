import os
import sys

# Тот самый костыль для protobuf. Оставляем, чтобы импорты внутри сгенерированных файлов не ломались.
protobufs_dir = os.path.join(os.path.dirname(__file__), 'protobufs')
if protobufs_dir not in sys.path:
    sys.path.insert(0, protobufs_dir)

from .protobufs.lens_overlay_filters_pb2 import LensOverlayFilterType, AppliedFilters, AppliedFilter
from .protobufs.lens_overlay_platform_pb2 import Platform
from .protobufs.lens_overlay_surface_pb2 import Surface
from .protobufs.lens_overlay_client_context_pb2 import LensOverlayClientContext, LocaleContext, RenderingContext, ClientLoggingData, LensRenderingEnvironment
from .protobufs.lens_overlay_client_logs_pb2 import LensOverlayClientLogs
from .protobufs.lens_overlay_client_platform_pb2 import ClientPlatform
from .protobufs.lens_overlay_geometry_pb2 import Geometry, CenterRotatedBox, ZoomedCrop
from .protobufs.lens_overlay_polygon_pb2 import Polygon, CoordinateType
from .protobufs.lens_overlay_text_pb2 import WritingDirection, Alignment, Text, TextLayout
from .protobufs.lens_overlay_deep_gleam_data_pb2 import DeepGleamData, TranslationData
from .protobufs.lens_overlay_interaction_request_metadata_pb2 import LensOverlayInteractionRequestMetadata
from .protobufs.lens_overlay_overlay_object_pb2 import OverlayObject
from .protobufs.lens_overlay_selection_type_pb2 import LensOverlaySelectionType
from .protobufs.lens_overlay_request_type_pb2 import RequestType
from .protobufs.lens_overlay_server_pb2 import LensOverlayServerError, LensOverlayServerRequest, LensOverlayServerResponse
from .protobufs.lens_overlay_service_deps_pb2 import LensOverlayObjectsResponse, LensOverlayObjectsRequest, LensOverlayRequestContext, LensOverlayInteractionRequest, LensOverlayInteractionResponse
from .protobufs.lens_overlay_phase_latencies_metadata_pb2 import LensOverlayPhaseLatenciesMetadata
from .protobufs.lens_overlay_routing_info_pb2 import LensOverlayRoutingInfo
from .protobufs.lens_overlay_cluster_info_pb2 import LensOverlayClusterInfo
from .protobufs.lens_overlay_document_pb2 import LensOverlayDocument, Page
from .protobufs.lens_overlay_payload_pb2 import ClientImage
from .protobufs.lens_overlay_image_crop_pb2 import ImageCrop
from .protobufs.lens_overlay_image_data_pb2 import ImageData, ImagePayload, ImageMetadata
from .protobufs.lens_overlay_text_query_pb2 import TextQuery
from .protobufs.lens_overlay_stickiness_signals_pb2 import StickinessSignals
from .protobufs.lens_overlay_video_context_input_params_pb2 import LensOverlayVideoContextInputParams
from .protobufs.lens_overlay_video_params_pb2 import LensOverlayVideoParams
from .protobufs.lens_overlay_visual_search_interaction_log_data_pb2 import LensOverlayVisualSearchInteractionLogData, FilterData, UserSelectionData
from .protobufs.lens_overlay_visual_search_interaction_data_pb2 import LensOverlayVisualSearchInteractionData
from .protobufs.lens_overlay_request_id_pb2 import LensOverlayRequestId
from .protobufs.aim_query_pb2 import QueryPayload, ModelMode, ToolMode

# Алиасы для обратной совместимости, так как betterproto делал классы плоскими, 
# а в google.protobuf они вложенные (Nested)
TextLayoutLine = TextLayout.Line
TextLayoutParagraph = TextLayout.Paragraph
TextLayoutWord = TextLayout.Word
TranslationDataStatusCode = TranslationData.Status 
LensOverlayInteractionRequestMetadataType = LensOverlayInteractionRequestMetadata.Type
PolygonVertexOrdering = Polygon.VertexOrdering

__all__ = [
    "LensOverlayFilterType", "AppliedFilters", "AppliedFilter", "Platform", "Surface",
    "LensOverlayClientContext", "LocaleContext", "RenderingContext", "ClientLoggingData",
    "LensRenderingEnvironment", "LensOverlayClientLogs", "ClientPlatform", "CoordinateType",
    "Geometry", "CenterRotatedBox", "ZoomedCrop", "Polygon", "WritingDirection", "Alignment",
    "Text", "TextLayout", "DeepGleamData", "TranslationData", "LensOverlayInteractionRequestMetadata",
    "OverlayObject", "LensOverlaySelectionType", "RequestType", "LensOverlayServerError",
    "LensOverlayServerRequest", "LensOverlayServerResponse", "LensOverlayObjectsResponse",
    "LensOverlayPhaseLatenciesMetadata", "LensOverlayRoutingInfo", "LensOverlayClusterInfo",
    "LensOverlayDocument", "Page", "ClientImage", "ImageCrop", "ImageData", "ImagePayload",
    "ImageMetadata", "TextQuery", "StickinessSignals", "LensOverlayVideoContextInputParams",
    "LensOverlayVideoParams", "LensOverlayVisualSearchInteractionLogData", "FilterData",
    "UserSelectionData", "LensOverlayVisualSearchInteractionData", "LensOverlayRequestId",
    "LensOverlayObjectsRequest", "LensOverlayRequestContext", "LensOverlayInteractionRequest",
    "LensOverlayInteractionResponse", "QueryPayload", "ModelMode", "ToolMode",
    "TextLayoutLine", "TextLayoutParagraph", "TextLayoutWord", "TranslationDataStatusCode",
    "LensOverlayInteractionRequestMetadataType", "PolygonVertexOrdering"
]