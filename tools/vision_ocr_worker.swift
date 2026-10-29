import Foundation
import Vision

struct Input: Decodable {
    let image_path: String
    let language: String?
}

while let line = readLine() {
    do {
        let input = try JSONDecoder().decode(Input.self, from: Data(line.utf8))
        let started = Date()
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .fast
        request.usesLanguageCorrection = false
        if let language = input.language, !language.isEmpty {
            request.recognitionLanguages = [language]
        }

        let handler = VNImageRequestHandler(
            url: URL(fileURLWithPath: input.image_path),
            options: [:]
        )
        try handler.perform([request])

        let detections = (request.results ?? []).compactMap { observation -> [String: Any]? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let box = observation.boundingBox
            return [
                "text": candidate.string,
                "x": box.origin.x,
                "y": 1.0 - box.origin.y - box.size.height,
                "width": box.size.width,
                "height": box.size.height,
                "confidence": candidate.confidence,
                "granularity": "line"
            ]
        }
        let sorted = detections.sorted {
            let y0 = ($0["y"] as? Double ?? 0)
            let y1 = ($1["y"] as? Double ?? 0)
            if abs(y0 - y1) > 0.008 { return y0 < y1 }
            return ($0["x"] as? Double ?? 0) < ($1["x"] as? Double ?? 0)
        }
        let output: [String: Any] = [
            "detections": sorted,
            "granularity": "line",
            "elapsed_ms": Date().timeIntervalSince(started) * 1000.0
        ]
        let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8) ?? "{}")
    } catch {
        let output = ["error": String(describing: error)]
        let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8) ?? "{}")
    }
}
