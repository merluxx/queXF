<?php

include_once("../config.inc.php");
//include_once("../db.inc.php");
//include ("../functions/functions.output.php");
include ("generate_zip_lib.php");

ignore_user_abort(true);
set_time_limit(0);

$qid = intval($argv[1] ?? 0);
$add_scan = ($argv[2] ?? "0") === "1";
$jobId = $argv[3] ?? "";

$tmpBase = rtrim(TEMPORARY_DIRECTORY, DIRECTORY_SEPARATOR);

$jobDir = $tmpBase . DIRECTORY_SEPARATOR . "jobs";

$statusFile = $jobDir . DIRECTORY_SEPARATOR . $jobId . ".json";

function update_status($statusFile, $data) {
    file_put_contents($statusFile, json_encode($data));
}

try {

    $response = generate_filled_pdf_zip($qid, $add_scan);

    if ($response["success"]) {

        update_status($statusFile, [
            "status" => "done",
            "downloadUrl" => $response["downloadUrl"]
        ]);

    } else {

        update_status($statusFile, [
            "status" => "error",
            "message" => $response["message"]
        ]);

    }

} catch (Throwable $e) {

    update_status($statusFile, [
        "status" => "error",
        "message" => $e->getMessage()
    ]);

}
