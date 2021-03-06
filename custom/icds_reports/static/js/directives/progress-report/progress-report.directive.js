/* global _ */

var url = hqImport('hqwebapp/js/initial_page_data').reverse;

function ProgressReportController($scope, $location, progressReportService,
                                  storageService, $routeParams, userLocationId, DTOptionsBuilder, DTColumnDefBuilder) {
    var vm = this;
    if (Object.keys($location.search()).length === 0) {
        $location.search(storageService.getKey('search'));
    } else {
        storageService.setKey('search', $location.search());
    }
    vm.userLocationId = userLocationId;
    vm.selectedLocations = [];

    vm.filtersData = $location.search();
    vm.filters = ['gender', 'age'];
    vm.label = "ICDS-CAS Fact Sheets";
    vm.data = [];
    vm.dates = [];
    vm.now = new Date().getMonth() + 1;
    vm.showWarning = storageService.getKey('search')['month'] === void(0) || vm.now === parseInt(storageService.getKey('search')['month']);
    vm.report = $routeParams.report;

    vm.prevDay = moment().subtract(1, 'days').format('Do MMMM, YYYY');
    vm.currentMonth = moment().format("MMMM");

    vm.showInfoMessage = function () {
        var selected_month = parseInt($location.search()['month']) || new Date().getMonth() + 1;
        var selected_year =  parseInt($location.search()['year']) || new Date().getFullYear();
        var current_month = new Date().getMonth() + 1;
        var current_year = new Date().getFullYear();
        return selected_month === current_month && selected_year === current_year && new Date().getDate() === 1;
    };

    vm.dtOptions = DTOptionsBuilder
        .newOptions()
        .withOption('scrollY', '400px')
        .withOption('scrollX', false)
        .withOption('scrollCollapse', true)
        .withOption('paging', false)
        .withOption('order', false)
        .withOption('sortable', false)
        .withDOM('<t>');

    vm.dtColumnDefs = [
        DTColumnDefBuilder.newColumnDef(0).notSortable(),
        DTColumnDefBuilder.newColumnDef(1).notSortable(),
        DTColumnDefBuilder.newColumnDef(2).notSortable(),
        DTColumnDefBuilder.newColumnDef(3).notSortable(),
        DTColumnDefBuilder.newColumnDef(4).notSortable(),
    ];
    vm.showTable = true;

    $scope.$on('filtersChange', function() {
        vm.showWarning = vm.now === storageService.getKey('search')['month'];
        vm.loadData();
    });

    $scope.$watch(function() {
        return vm.selectedLocations;
    }, function (newValue, oldValue) {
        if (newValue === oldValue || !newValue || newValue.length === 0) {
            return;
        }
        if (newValue.length === 6) {
            var parent = newValue[3];
            $location.search('location_id', parent.location_id);
            $location.search('selectedLocationLevel', 3);
            $location.search('location_name', parent.name);
            storageService.setKey('message', true);
            setTimeout(function() {
                storageService.setKey('message', false);
            }, 3000);
        }
        return newValue;
    }, true);

    vm.loadData = function () {
        if (!vm.report) {
            return;
        }
        var params = window.angular.copy(vm.filtersData);
        params.category = vm.report;
        vm.myPromise = progressReportService.getData(params).then(function(response) {
            vm.title = response.data.config.title;
            vm.data = response.data.config.sections;
        });
    };

    vm.sumValues = function(values) {
        var sum = _.reduce(values, function(memo, num) { return memo + num; }, 0);
        return sum / values.length;
    };

    vm.getCSS = function(data, index, reverse) {
        if (index === 0 || index === 1) {
            return 'black';
        }

        var currentData = data[index].html;
        var previousMonthData = data[index - 1].html;

        var colors = (reverse ? ['red', 'green'] : ['green', 'red']);

        if (currentData === previousMonthData) {
            return 'black';
        } else if (previousMonthData < currentData) {
            return colors[0] + ' fa fa-arrow-up';
        } else if (previousMonthData > currentData) {
            return colors[1] + ' fa fa-arrow-down';
        }
    };

    vm.getDisableIndex = function () {
        var i = -1;
        window.angular.forEach(vm.selectedLocations, function (key, value) {
            if (key !== null && key.location_id === vm.userLocationId) {
                i = value;
            }
        });
        return i;
    };


    vm.moveToLocation = function(loc, index) {
        if (loc === 'national') {
            $location.search('location_id', '');
            $location.search('selectedLocationLevel', -1);
            $location.search('location_name', '');
        } else {
            $location.search('location_id', loc.location_id);
            $location.search('selectedLocationLevel', index);
            $location.search('location_name', loc.name);
        }
    };

    vm.goToReport = function(reportName) {
        $location.path('fact_sheets/' + reportName);
    };

    vm.goBack = function() {
        vm.report = null;
        vm.title = null;
        $location.path('fact_sheets/');
    };

    vm.loadData();
}

ProgressReportController.$inject = [
    '$scope', '$location', 'progressReportService', 'storageService', '$routeParams', 'userLocationId', 'DTOptionsBuilder', 'DTColumnDefBuilder',
];

window.angular.module('icdsApp').directive('progressReport', function() {
    return {
        restrict: 'E',
        templateUrl: url('icds-ng-template', 'progress-report.directive'),
        bindToController: true,
        controller: ProgressReportController,
        controllerAs: '$ctrl',
    };
});
